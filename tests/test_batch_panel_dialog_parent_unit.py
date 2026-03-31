# -*- coding: utf-8 -*-
"""BatchPanel dialog parenting regressions for embedded water-profile usage."""

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _install_batch_panel_import_stubs():
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class _FakeFileDialog:
        @staticmethod
        def getOpenFileName(*args, **kwargs):
            return ("", "")

        @staticmethod
        def getSaveFileName(*args, **kwargs):
            return ("", "")

    qtwidgets.QFileDialog = _FakeFileDialog
    for name in (
        "QWidget",
        "QVBoxLayout",
        "QHBoxLayout",
        "QLabel",
        "QGroupBox",
        "QSplitter",
        "QFrame",
        "QTabWidget",
        "QTextEdit",
        "QTableWidget",
        "QTableWidgetItem",
        "QHeaderView",
        "QComboBox",
        "QAbstractItemView",
        "QApplication",
        "QMenu",
        "QDialog",
        "QDialogButtonBox",
        "QGridLayout",
        "QFormLayout",
    ):
        setattr(qtwidgets, name, type(name, (), {}))

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.Qt = SimpleNamespace()
    qtcore.Signal = lambda *args, **kwargs: None

    qtgui = types.ModuleType("PySide6.QtGui")
    for name in ("QFont", "QColor", "QShortcut", "QKeySequence"):
        setattr(qtgui, name, type(name, (), {}))

    sys.modules.setdefault("PySide6", types.ModuleType("PySide6"))
    sys.modules["PySide6.QtWidgets"] = qtwidgets
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui

    qfw = types.ModuleType("qfluentwidgets")
    for name in (
        "PushButton",
        "PrimaryPushButton",
        "DropDownPushButton",
        "CheckBox",
        "InfoBar",
        "InfoBarPosition",
        "LineEdit",
        "ComboBox",
        "RoundMenu",
        "Action",
    ):
        setattr(qfw, name, type(name, (), {}))
    sys.modules["qfluentwidgets"] = qfw

    styles_mod = types.ModuleType("app_渠系计算前端.styles")
    styles_mod.P = styles_mod.S = styles_mod.W = styles_mod.E = ""
    styles_mod.BG = styles_mod.CARD = styles_mod.BD = styles_mod.T1 = styles_mod.T2 = ""
    styles_mod.DIALOG_STYLE = ""
    styles_mod.auto_resize_table = lambda *args, **kwargs: None
    styles_mod.fluent_info = lambda *args, **kwargs: None
    styles_mod.fluent_error = lambda *args, **kwargs: None
    styles_mod.fluent_question = lambda *args, **kwargs: True
    styles_mod.fluent_batch_result = lambda *args, **kwargs: None
    sys.modules["app_渠系计算前端.styles"] = styles_mod

    frozen_mod = types.ModuleType("app_渠系计算前端.frozen_table")
    frozen_mod.FrozenColumnTableWidget = type("FrozenColumnTableWidget", (), {})
    sys.modules["app_渠系计算前端.frozen_table"] = frozen_mod

    export_mod = types.ModuleType("app_渠系计算前端.export_utils")
    export_mod.WORD_EXPORT_AVAILABLE = False
    for name in (
        "ask_open_file",
        "create_styled_doc",
        "doc_add_h1",
        "doc_add_h2",
        "doc_add_body",
        "doc_add_styled_table",
        "doc_add_table_caption",
        "doc_add_param_table",
        "doc_render_calc_text",
        "update_doc_toc_via_com",
    ):
        setattr(export_mod, name, lambda *args, **kwargs: None)
    sys.modules["app_渠系计算前端.export_utils"] = export_mod

    selector_mod = types.ModuleType("app_渠系计算前端.structure_type_selector")
    selector_mod.StructureTypeSelector = type("StructureTypeSelector", (), {})
    sys.modules["app_渠系计算前端.structure_type_selector"] = selector_mod

    shared_mod = types.ModuleType("shared.shared_data_manager")
    shared_mod.get_shared_data_manager = lambda: SimpleNamespace(clear_batch_results=lambda: None)
    sys.modules["shared.shared_data_manager"] = shared_mod

    mingqu_mod = types.ModuleType("明渠设计")
    mingqu_mod.quick_calculate = lambda *args, **kwargs: {}
    mingqu_mod.quick_calculate_circular = lambda *args, **kwargs: {}
    mingqu_mod.quick_calculate_u_section = lambda *args, **kwargs: {}
    sys.modules["明渠设计"] = mingqu_mod

    ducao_mod = types.ModuleType("渡槽设计")
    ducao_mod.quick_calculate_u = lambda *args, **kwargs: {}
    ducao_mod.quick_calculate_rect = lambda *args, **kwargs: {}
    sys.modules["渡槽设计"] = ducao_mod

    tunnel_mod = types.ModuleType("隧洞设计")
    tunnel_mod.quick_calculate_circular = lambda *args, **kwargs: {}
    tunnel_mod.quick_calculate_horseshoe = lambda *args, **kwargs: {}
    tunnel_mod.quick_calculate_horseshoe_std = lambda *args, **kwargs: {}
    sys.modules["隧洞设计"] = tunnel_mod

    culvert_mod = types.ModuleType("矩形暗涵设计")
    culvert_mod.quick_calculate_rectangular_culvert = lambda *args, **kwargs: {}
    sys.modules["矩形暗涵设计"] = culvert_mod


def _load_batch_panel_module():
    patched_names = [
        "PySide6",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "qfluentwidgets",
        "app_渠系计算前端.styles",
        "app_渠系计算前端.frozen_table",
        "app_渠系计算前端.export_utils",
        "app_渠系计算前端.structure_type_selector",
        "shared.shared_data_manager",
        "明渠设计",
        "渡槽设计",
        "隧洞设计",
        "矩形暗涵设计",
    ]
    saved_modules = {name: sys.modules.get(name) for name in patched_names}
    try:
        _install_batch_panel_import_stubs()
        panel_path = next(Path(".").glob("**/batch/panel.py")).resolve()
        spec = importlib.util.spec_from_file_location("batch_panel_dialog_parent_test_mod", panel_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old_module in saved_modules.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


class _FakeLineEdit:
    def __init__(self):
        self.value = ""

    def setText(self, text):
        self.value = str(text)


class _FakeComboBox:
    def __init__(self):
        self.index = -1

    def findText(self, text):
        _ = text
        return 0

    def setCurrentIndex(self, index):
        self.index = index


class _FakeInputTable:
    def __init__(self, rows):
        self._rows = rows

    def rowCount(self):
        return self._rows

    def setRowCount(self, rows):
        self._rows = rows


class _FakeToggle:
    def __init__(self, checked=False):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _FakeResultItem:
    def __init__(self, text=""):
        self._text = str(text)
        self.alignment = None
        self.foreground = None

    def text(self):
        return self._text

    def setTextAlignment(self, alignment):
        self.alignment = alignment

    def setForeground(self, foreground):
        self.foreground = foreground


class _FakeResultTable:
    def __init__(self, columns):
        self._columns = columns
        self._rows = []

    def rowCount(self):
        return len(self._rows)

    def setRowCount(self, count):
        while len(self._rows) < count:
            self._rows.append([None] * self._columns)
        while len(self._rows) > count:
            self._rows.pop()

    def setItem(self, row, col, item):
        self._rows[row][col] = item

    def item(self, row, col):
        if row < 0 or row >= len(self._rows):
            return None
        if col < 0 or col >= self._columns:
            return None
        return self._rows[row][col]


class _FakeNotebook:
    def __init__(self):
        self.current_index = None

    def setCurrentIndex(self, index):
        self.current_index = index


class _FakeCell:
    def __init__(self, value):
        self.value = value


class _FakeWorksheet:
    def __init__(self, cells, max_row):
        self._cells = cells
        self.max_row = max_row

    def cell(self, row, column):
        return _FakeCell(self._cells.get((row, column)))


class _FakeWorkbook:
    def __init__(self, sheet):
        self.active = sheet


def _make_fake_openpyxl(module):
    header_row = {
        (1, 1): "渠道名称",
        (1, 2): "苏溪",
        (1, 3): "渠道级别",
        (1, 4): "支渠",
        (1, 5): "起始水位",
        (1, 6): "369.5",
        (1, 8): "0+000.000",
        (2, 5): "X",
        (2, 7): "Q(m3/s)",
    }
    data_row = {
        (3, 1): "1",
        (3, 2): "1",
        (3, 3): "建筑物A",
        (3, 4): "明渠-圆形",
        (3, 5): "3387608.310826",
        (3, 6): "658796.619323",
        (3, 7): "0.27",
        (3, 8): "0.014",
        (3, 9): "3000",
    }
    sheet = _FakeWorksheet({**header_row, **data_row}, max_row=3)
    fake_openpyxl = types.ModuleType("openpyxl")
    fake_openpyxl.load_workbook = lambda *args, **kwargs: _FakeWorkbook(sheet)
    return fake_openpyxl


def _make_input_row(module, *, section_type, building_name="穿路段", q="1.2", n="", slope="", d="1.4"):
    row = [""] * len(module.INPUT_HEADERS)
    row[0] = "1"
    row[1] = "2"
    row[2] = building_name
    row[3] = section_type
    row[4] = "451333.9116"
    row[5] = "3047880.2791"
    row[6] = q
    row[7] = n
    row[8] = slope
    row[13] = d
    return row


def test_import_prompt_uses_visible_host_parent(monkeypatch):
    module = _load_batch_panel_module()
    BatchPanel = module.BatchPanel
    panel = BatchPanel.__new__(BatchPanel)
    host = object()
    captured = {}

    BatchPanel.set_info_parent(panel, lambda: host)
    panel._has_opened_template = False
    panel._last_import_dir = None
    panel._save_user_prefs = lambda: captured.setdefault("saved", True)
    panel._open_excel_template = lambda: captured.setdefault("opened_template", True)

    def fake_question(parent, title, content, yes_text="是", no_text="否"):
        captured["question_parent"] = parent
        captured["question_title"] = title
        captured["yes_text"] = yes_text
        captured["no_text"] = no_text
        captured["content"] = content
        return False

    def fake_get_open_file_name(parent, title, initial_dir, filters):
        captured["file_parent"] = parent
        captured["file_title"] = title
        captured["initial_dir"] = initial_dir
        captured["filters"] = filters
        return ("", "")

    monkeypatch.setattr(module, "fluent_question", fake_question)
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", staticmethod(fake_get_open_file_name))

    BatchPanel._import_from_excel(panel)

    assert captured["question_parent"] is host
    assert captured["question_title"] == "导入Excel"
    assert captured["file_parent"] is host
    assert captured["file_title"] == "选择Excel文件"
    assert panel._has_opened_template is True


def test_sample_overwrite_prompt_uses_visible_host_parent(monkeypatch):
    module = _load_batch_panel_module()
    BatchPanel = module.BatchPanel
    panel = BatchPanel.__new__(BatchPanel)
    host = object()
    captured = {}

    BatchPanel.set_info_parent(panel, lambda: host)
    panel._is_sample_data = False
    panel.input_table = _FakeInputTable(rows=3)
    panel.channel_name_edit = _FakeLineEdit()
    panel.channel_level_combo = _FakeComboBox()
    panel.start_wl_edit = _FakeLineEdit()
    panel.start_station_edit = _FakeLineEdit()
    panel._info_parent_override = lambda: host

    fake_openpyxl = _make_fake_openpyxl(module)
    monkeypatch.setitem(sys.modules, "openpyxl", fake_openpyxl)

    def fake_question(parent, title, content, yes_text="是", no_text="否"):
        captured["question_parent"] = parent
        captured["question_title"] = title
        captured["yes_text"] = yes_text
        captured["no_text"] = no_text
        captured["content"] = content
        return False

    monkeypatch.setattr(module, "fluent_question", fake_question)

    BatchPanel._do_load_from_filepath(
        panel,
        filepath="sample.xlsx",
        is_sample=True,
        sample_title="示例一",
        sample_desc="综合演示数据",
    )

    assert captured["question_parent"] is host
    assert captured["question_title"] == "确认覆盖"
    assert captured["yes_text"] == "覆盖导入"


def test_batch_calculate_routes_exception_details_to_visible_host_summary(monkeypatch):
    module = _load_batch_panel_module()
    BatchPanel = module.BatchPanel
    panel = BatchPanel.__new__(BatchPanel)
    host = object()
    captured = {}

    BatchPanel.set_info_parent(panel, lambda: host)
    module.QTableWidgetItem = _FakeResultItem
    module.QColor = lambda value: value
    module.Qt = SimpleNamespace(AlignCenter=0x0004)
    module.InfoBar = SimpleNamespace(
        warning=lambda *args, **kwargs: None,
        success=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: captured.setdefault("info_calls", []).append((args, kwargs)),
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.SHARED_DATA_AVAILABLE = False

    row = _make_input_row(module, section_type="明渠-梯形", n="", slope="")
    panel._get_all_input_data = lambda: [row]
    panel._validate_duplicate_buildings = lambda _rows: True
    panel._clear_results = lambda: panel.result_table.setRowCount(0)
    panel._normalize_row = lambda values, length: list(values[:length]) + [""] * max(0, length - len(values))
    panel._sync_common_columns = lambda: None
    panel._update_lock_state = lambda has_errors: captured.setdefault("lock_state", has_errors)
    panel._sf = lambda value, default=0.0: float(value) if str(value).strip() else default
    panel.result_table = _FakeResultTable(len(module.RESULT_HEADERS))
    panel.result_notebook = _FakeNotebook()
    panel.detail_text = SimpleNamespace(setPlainText=lambda *_args, **_kwargs: None)
    panel.detail_cb = _FakeToggle(False)
    panel.inc_cb = _FakeToggle(False)
    panel.batch_results = []
    panel._last_calc_snapshot = None
    panel._last_calc_detail = False

    def fake_batch_result(parent, title, summary, details):
        captured["batch_parent"] = parent
        captured["title"] = title
        captured["summary"] = summary
        captured["details"] = details

    monkeypatch.setattr(module, "fluent_batch_result", fake_batch_result)
    monkeypatch.setattr(
        module,
        "fluent_info",
        lambda *args, **kwargs: captured.setdefault("plain_info_calls", []).append((args, kwargs)),
    )

    BatchPanel._batch_calculate(panel)

    assert captured["batch_parent"] is host
    assert captured["title"] == "批量计算完成 (存在异常)"
    assert "糙率n必须大于0" in captured["details"]
    assert "plain_info_calls" not in captured


def test_batch_calculate_treats_directional_drill_as_pressure_pipe_like_placeholder(monkeypatch):
    module = _load_batch_panel_module()
    BatchPanel = module.BatchPanel
    panel = BatchPanel.__new__(BatchPanel)
    captured = {}

    module.QTableWidgetItem = _FakeResultItem
    module.QColor = lambda value: value
    module.Qt = SimpleNamespace(AlignCenter=0x0004)
    module.InfoBar = SimpleNamespace(
        warning=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        success=lambda *args, **kwargs: captured.setdefault("success_calls", []).append((args, kwargs)),
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.SHARED_DATA_AVAILABLE = False

    row = _make_input_row(module, section_type="定向钻", n="", slope="")
    panel._get_all_input_data = lambda: [row]
    panel._validate_duplicate_buildings = lambda _rows: True
    panel._clear_results = lambda: panel.result_table.setRowCount(0)
    panel._normalize_row = lambda values, length: list(values[:length]) + [""] * max(0, length - len(values))
    panel._sync_common_columns = lambda: None
    panel._update_lock_state = lambda has_errors: captured.setdefault("lock_state", has_errors)
    panel._sf = lambda value, default=0.0: float(value) if str(value).strip() else default
    panel.result_table = _FakeResultTable(len(module.RESULT_HEADERS))
    panel.result_notebook = _FakeNotebook()
    panel.detail_text = SimpleNamespace(setPlainText=lambda *_args, **_kwargs: None)
    panel.detail_cb = _FakeToggle(False)
    panel.inc_cb = _FakeToggle(False)
    panel.batch_results = []
    panel._last_calc_snapshot = None
    panel._last_calc_detail = False

    monkeypatch.setattr(
        module,
        "fluent_batch_result",
        lambda *args, **kwargs: captured.setdefault("failure_dialog_calls", []).append((args, kwargs)),
    )
    monkeypatch.setattr(
        module,
        "fluent_info",
        lambda *args, **kwargs: captured.setdefault("plain_info_calls", []).append((args, kwargs)),
    )

    def _unexpected_calculate_single(*_args, **_kwargs):
        raise AssertionError("定向钻应按有压管道同类占位行处理，不应进入断面求解")

    panel._calculate_single = _unexpected_calculate_single

    BatchPanel._batch_calculate(panel)

    assert len(panel.batch_results) == 1
    result = panel.batch_results[0]["result"]
    assert result["is_pressure_pipe"] is True
    assert result["section_type"] == "定向钻"
    assert panel.result_table.item(0, 3).text() == "定向钻"
    assert "占位行" in panel.result_table.item(0, len(module.RESULT_HEADERS) - 1).text()
    assert captured["lock_state"] is False
    assert "failure_dialog_calls" not in captured
    assert "plain_info_calls" not in captured


def test_get_template_path_returns_chating_sample_file():
    module = _load_batch_panel_module()
    BatchPanel = module.BatchPanel
    panel = BatchPanel.__new__(BatchPanel)

    template_path = BatchPanel._get_template_path(panel, "chating")
    sample_path = BatchPanel._get_sample5_path(panel)

    assert template_path.endswith("茶亭支渠批量计算.xlsx")
    assert sample_path.endswith("茶亭支渠批量计算.xlsx")
    assert template_path == sample_path


def test_get_template_path_returns_hezuo_sample_file():
    module = _load_batch_panel_module()
    BatchPanel = module.BatchPanel
    panel = BatchPanel.__new__(BatchPanel)

    template_path = BatchPanel._get_template_path(panel, "hezuo")
    sample_path = BatchPanel._get_sample6_path(panel)

    assert template_path.endswith("合作干渠批量计算用表.xlsx")
    assert sample_path.endswith("合作干渠批量计算用表.xlsx")
    assert template_path == sample_path


def test_get_template_path_returns_ganjiagou_sample_file():
    module = _load_batch_panel_module()
    BatchPanel = module.BatchPanel
    panel = BatchPanel.__new__(BatchPanel)

    template_path = BatchPanel._get_template_path(panel, "ganjiagou")
    sample_path = BatchPanel._get_sample7_path(panel)

    assert template_path.endswith("甘家沟充水渠批量计算用表.xlsx")
    assert sample_path.endswith("甘家沟充水渠批量计算用表.xlsx")
    assert template_path == sample_path
