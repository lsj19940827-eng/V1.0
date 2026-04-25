"""倒虹吸批量导出水头损失取值规则回归测试。"""

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "倒虹吸水力计算系统"))

from siphon_models import CalculationResult


class _FakeSignal:
    """测试用信号对象。"""

    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)


class _FakeDialog:
    """测试用对话框。"""

    last_instance = None

    def __init__(self, _parent=None):
        self.window_title = ""
        self.min_width = 0
        self.size = (0, 0)
        self.style = ""
        self.accepted = False
        _FakeDialog.last_instance = self

    def setWindowTitle(self, title):
        self.window_title = title

    def setMinimumWidth(self, width):
        self.min_width = width

    def resize(self, width, height):
        self.size = (width, height)

    def setStyleSheet(self, style):
        self.style = style

    def accept(self):
        self.accepted = True

    def exec(self):
        return 0


class _FakeLayout:
    """测试用布局。"""

    def __init__(self, _parent=None):
        self.widgets = []
        self.layouts = []
        self.margins = (0, 0, 0, 0)
        self.spacing = 0
        self.alignment = None

    def setContentsMargins(self, left, top, right, bottom):
        self.margins = (left, top, right, bottom)

    def setSpacing(self, spacing):
        self.spacing = spacing

    def setAlignment(self, alignment):
        self.alignment = alignment

    def addWidget(self, widget, *_args):
        self.widgets.append(widget)

    def addLayout(self, layout):
        self.layouts.append(layout)

    def addStretch(self):
        return None


class _FakeLabel:
    """测试用标签。"""

    def __init__(self, text=""):
        self.text = text
        self.style = ""
        self.word_wrap = False
        self.tooltip = ""

    def setStyleSheet(self, style):
        self.style = style

    def setWordWrap(self, value):
        self.word_wrap = bool(value)

    def setToolTip(self, tooltip):
        self.tooltip = tooltip


class _FakeHeader:
    """测试用表头。"""

    def __init__(self):
        self.last_stretch = None
        self.resize_modes = {}

    def setStretchLastSection(self, value):
        self.last_stretch = bool(value)

    def setSectionResizeMode(self, column, mode):
        self.resize_modes[column] = mode


class _FakeVerticalHeader:
    """测试用纵向表头。"""

    def __init__(self):
        self.visible = True

    def setVisible(self, value):
        self.visible = bool(value)


class _FakeTableWidget:
    """测试用表格。"""

    last_instance = None

    def __init__(self, rows, columns):
        self.rows = rows
        self.columns = columns
        self.headers = []
        self.items = {}
        self.cell_widgets = {}
        self.horizontal_header = _FakeHeader()
        self.vertical_header = _FakeVerticalHeader()
        self.selection_behavior = None
        self.edit_triggers = None
        self.font = None
        _FakeTableWidget.last_instance = self

    def setHorizontalHeaderLabels(self, labels):
        self.headers = list(labels)

    def horizontalHeader(self):
        return self.horizontal_header

    def verticalHeader(self):
        return self.vertical_header

    def setColumnWidth(self, _column, _width):
        return None

    def setSelectionBehavior(self, behavior):
        self.selection_behavior = behavior

    def setEditTriggers(self, triggers):
        self.edit_triggers = triggers

    def setFont(self, font):
        self.font = font

    def setCellWidget(self, row, column, widget):
        self.cell_widgets[(row, column)] = widget

    def setItem(self, row, column, item):
        self.items[(row, column)] = item


class _FakeTableWidgetItem:
    """测试用单元格。"""

    def __init__(self, text=""):
        self.text = text
        self.alignment = None

    def setTextAlignment(self, alignment):
        self.alignment = alignment


class _FakeCheckBox:
    """测试用复选框。"""

    def __init__(self):
        self.checked = False

    def setChecked(self, value):
        self.checked = bool(value)

    def isChecked(self):
        return self.checked


class _FakeWidget:
    """测试用空组件。"""

    def __init__(self, _parent=None):
        self.parent = _parent


class _FakeButton:
    """测试用按钮。"""

    def __init__(self, text=""):
        self.text = text
        self.clicked = _FakeSignal()
        self.tooltip = ""

    def setToolTip(self, tooltip):
        self.tooltip = tooltip


class _FakeFont:
    """测试用字体。"""

    def __init__(self, family="", size=0):
        self.family = family
        self.size = size


class _FakeNotebook:
    """测试用标签页。"""

    def count(self):
        return 0

    def tabText(self, _index):
        return ""

    def setCurrentIndex(self, _index):
        return None


_STUB_MODULE_NAMES = [
    "PySide6",
    "PySide6.QtWidgets",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "qfluentwidgets",
    "app_渠系计算前端.siphon.panel",
    "app_渠系计算前端.styles",
    "managers.siphon_manager",
    "utils.siphon_extractor",
    "推求水面线",
    "推求水面线.utils",
]


def _install_gui_stubs():
    """安装导入 multi_siphon_dialog 所需的最小桩。"""
    original_modules = {name: sys.modules.get(name) for name in _STUB_MODULE_NAMES}

    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    qtwidgets.QApplication = type(
        "QApplication",
        (),
        {"processEvents": staticmethod(lambda: None)},
    )
    qtwidgets.QDialog = _FakeDialog
    qtwidgets.QVBoxLayout = _FakeLayout
    qtwidgets.QHBoxLayout = _FakeLayout
    qtwidgets.QTabWidget = type("QTabWidget", (), {})
    qtwidgets.QLabel = _FakeLabel
    qtwidgets.QWidget = _FakeWidget
    qtwidgets.QProgressBar = type("QProgressBar", (), {})
    qtwidgets.QTableWidget = _FakeTableWidget
    qtwidgets.QTableWidgetItem = _FakeTableWidgetItem
    qtwidgets.QHeaderView = SimpleNamespace(
        Fixed="fixed",
        Stretch="stretch",
        ResizeToContents="resize_to_contents",
    )
    qtwidgets.QAbstractItemView = SimpleNamespace(
        SelectRows="select_rows",
        NoEditTriggers="no_edit",
    )
    qtwidgets.QCheckBox = _FakeCheckBox
    qtwidgets.QSizePolicy = type("QSizePolicy", (), {})
    qtwidgets.QFrame = type("QFrame", (), {})

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.Qt = SimpleNamespace(
        Window=0,
        WindowMinimized=1,
        WindowActive=2,
        Key_Escape=27,
        AlignCenter=0x0004,
        AlignLeft=0x0001,
        AlignVCenter=0x0080,
    )
    qtcore.QTimer = type("QTimer", (), {"singleShot": staticmethod(lambda *args, **kwargs: None)})

    qtgui = types.ModuleType("PySide6.QtGui")
    qtgui.QFont = _FakeFont

    sys.modules.setdefault("PySide6", types.ModuleType("PySide6"))
    sys.modules["PySide6.QtWidgets"] = qtwidgets
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui

    qfw = types.ModuleType("qfluentwidgets")
    qfw.PushButton = _FakeButton
    qfw.PrimaryPushButton = _FakeButton
    qfw.InfoBar = type("InfoBar", (), {"warning": staticmethod(lambda *args, **kwargs: None)})
    qfw.InfoBarPosition = SimpleNamespace(TOP="TOP")
    sys.modules["qfluentwidgets"] = qfw

    panel_mod = types.ModuleType("app_渠系计算前端.siphon.panel")
    panel_mod.SiphonPanel = type("SiphonPanel", (), {})
    sys.modules["app_渠系计算前端.siphon.panel"] = panel_mod

    styles_mod = types.ModuleType("app_渠系计算前端.styles")
    styles_mod.P = ""
    styles_mod.S = ""
    styles_mod.T1 = "#000000"
    styles_mod.T2 = "#666666"
    styles_mod.BD = "#dddddd"
    styles_mod.DIALOG_STYLE = ""
    styles_mod.auto_resize_table = lambda *args, **kwargs: None
    sys.modules["app_渠系计算前端.styles"] = styles_mod

    managers_mod = types.ModuleType("managers.siphon_manager")
    managers_mod.SiphonManager = type("SiphonManager", (), {})
    managers_mod.SiphonConfig = type("SiphonConfig", (), {})
    sys.modules["managers.siphon_manager"] = managers_mod

    extractor_mod = types.ModuleType("utils.siphon_extractor")
    extractor_mod.SiphonDataExtractor = type("SiphonDataExtractor", (), {})
    extractor_mod.SiphonGroup = type("SiphonGroup", (), {})
    sys.modules["utils.siphon_extractor"] = extractor_mod

    utils_pkg = types.ModuleType("推求水面线.utils")
    sys.modules["推求水面线.utils"] = utils_pkg
    sys.modules.setdefault("推求水面线", types.ModuleType("推求水面线"))
    sys.modules["推求水面线"].utils = utils_pkg

    return original_modules


def _restore_modules(original_modules):
    """恢复被桩替换的模块，避免影响其他测试。"""
    for name, module in original_modules.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _load_dialog_class():
    """加载 MultiSiphonDialog。"""
    original_modules = _install_gui_stubs()
    sys.modules.pop("app_渠系计算前端.siphon.multi_siphon_dialog", None)
    try:
        mod = importlib.import_module("app_渠系计算前端.siphon.multi_siphon_dialog")
        return mod.MultiSiphonDialog
    finally:
        sys.modules.pop("app_渠系计算前端.siphon.multi_siphon_dialog", None)
        _restore_modules(original_modules)


def _make_panel(result):
    """构造最小面板替身。"""
    return SimpleNamespace(
        calculation_result=result,
        get_result=lambda: result,
        get_plan_bend_radius=lambda: 3.0,
        has_excel_turn_radius_override=lambda: False,
        summary_text=SimpleNamespace(setPlainText=lambda *_args, **_kwargs: None),
        detail_text=SimpleNamespace(setPlainText=lambda *_args, **_kwargs: None),
        result_notebook=SimpleNamespace(setCurrentIndex=lambda *_args, **_kwargs: None),
        _suppress_result_display=True,
    )


def test_batch_export_uses_design_head_loss_when_increase_is_disabled():
    """未启用加大流量时，应回写设计工况总水头损失。"""
    MultiSiphonDialog = _load_dialog_class()
    result = CalculationResult(total_head_loss=1.2345)

    assert MultiSiphonDialog._get_export_head_loss(result) == pytest.approx(1.2345)


def test_batch_export_uses_increased_head_loss_when_increase_is_enabled():
    """启用加大流量时，应回写加大工况总水头损失。"""
    MultiSiphonDialog = _load_dialog_class()
    result = CalculationResult(
        total_head_loss=1.2345,
        increase_percent=15.0,
        total_head_loss_inc=2.3456,
    )

    assert MultiSiphonDialog._get_export_head_loss(result) == pytest.approx(2.3456)


def test_summary_dialog_and_export_results_share_same_head_loss_rule():
    """汇总弹窗与导出结果应复用同一套水头损失取值规则。"""
    MultiSiphonDialog = _load_dialog_class()
    result = CalculationResult(total_head_loss=1.2345)
    panel = _make_panel(result)

    fake_dialog = SimpleNamespace(
        panels={"虹吸A": panel},
        notebook=_FakeNotebook(),
        _on_close=lambda: None,
        _get_export_head_loss=MultiSiphonDialog._get_export_head_loss,
    )

    exported = MultiSiphonDialog._get_all_results(fake_dialog)

    assert exported["虹吸A"]["head_loss"] == pytest.approx(1.2345)

    MultiSiphonDialog._show_summary_dialog(fake_dialog, [("虹吸A", panel)], fail_count=0, imported_count=1)

    assert _FakeTableWidget.last_instance is not None
    assert _FakeTableWidget.last_instance.items[(0, 3)].text == "1.2345"


def test_result_callback_uses_same_export_head_loss_rule_for_save_and_status():
    MultiSiphonDialog = _load_dialog_class()
    saved = {}
    statuses = []

    fake_dialog = SimpleNamespace(
        manager=SimpleNamespace(
            update_siphon_result=lambda *args: saved.setdefault("args", args),
            save_config=lambda: saved.setdefault("saved", True),
        ),
        _get_export_head_loss=MultiSiphonDialog._get_export_head_loss,
        _update_time_label=lambda: saved.setdefault("time_label", True),
        _update_status=lambda text: statuses.append(text),
    )

    callback = MultiSiphonDialog._make_result_callback(fake_dialog, "虹吸A")
    result = CalculationResult(
        total_head_loss=1.2345,
        increase_percent=15.0,
        total_head_loss_inc=2.3456,
        diameter=0.6,
        velocity=1.8,
    )

    callback(result)

    assert saved["args"] == ("虹吸A", pytest.approx(2.3456), 0.6, 1.8)
    assert statuses == ["虹吸A: 总水头损失 = 2.3456 m"]
