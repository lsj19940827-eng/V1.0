# -*- coding: utf-8 -*-
"""批量页复式梯形支持的单元测试。"""

import os
import sys
import tempfile
import types
from pathlib import Path

from PySide6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.batch.panel import BatchPanel, INPUT_HEADERS, SECTION_TYPES, SectionParameterDialog
import app_渠系计算前端.batch.panel as batch_panel_mod


def _get_qapp():
    app = QApplication.instance() or QApplication([])
    # 避免最后一个测试窗口关闭时触发 QApplication 提前退出，导致 pytest 进程崩溃。
    app.setQuitOnLastWindowClosed(False)
    return app


def _flush_events(rounds=4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _prepare_panel(monkeypatch):
    _get_qapp()

    class _InfoBarStub:
        @staticmethod
        def success(*args, **kwargs):
            return None

        @staticmethod
        def warning(*args, **kwargs):
            return None

        @staticmethod
        def error(*args, **kwargs):
            return None

        @staticmethod
        def info(*args, **kwargs):
            return None

    monkeypatch.setattr(batch_panel_mod, "InfoBar", _InfoBarStub)
    monkeypatch.setattr(batch_panel_mod, "fluent_batch_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *args, **kwargs: None)

    panel = BatchPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)
    panel._clear_input(force=True)
    _flush_events(2)
    return panel


def test_batch_panel_supports_compound_trapezoid_dialog_dispatch_and_excel_import(monkeypatch):
    """批量页应支持新类型、参数弹窗、计算分发和 Excel 导入。"""
    assert "明渠-复式梯形" in SECTION_TYPES

    dialog = SectionParameterDialog(None, "明渠-复式梯形", {})
    for key in ("m1", "B1", "m2", "B2", "m3", "h1"):
        assert key in dialog._entries

    panel = _prepare_panel(monkeypatch)

    result = panel._calculate_single(
        "明渠-复式梯形",
        8.391,
        0.014,
        3000,
        0.1,
        100.0,
        m1=1.5,
        B1=2.0,
        m2=1.0,
        B2=3.0,
        m3=1.0,
        h1=1.0,
        manual_increase_percent=20.0,
    )

    assert result["success"] is True

    fake_cells = {
        (1, 1): "渠道名称",
        (1, 2): "测试渠道",
        (1, 3): "渠道级别",
        (1, 4): "支渠",
        (1, 5): "起始水位",
        (1, 6): "369.5",
        (1, 8): "0+000.000",
    }
    for column, header in enumerate(INPUT_HEADERS, start=1):
        fake_cells[(2, column)] = header
    header_index = {header: idx + 1 for idx, header in enumerate(INPUT_HEADERS)}
    fake_cells[(3, header_index["序号"])] = "1"
    fake_cells[(3, header_index["流量段"])] = "1"
    fake_cells[(3, header_index["建筑物名称"])] = "-"
    fake_cells[(3, header_index["结构形式"])] = "明渠-复式梯形"
    fake_cells[(3, header_index["Q(m³/s)"])] = "8.391"
    fake_cells[(3, header_index["糙率n"])] = "0.014"
    fake_cells[(3, header_index["比降(1/)"])] = "3000"
    fake_cells[(3, header_index["不淤流速"])] = "0.1"
    fake_cells[(3, header_index["不冲流速"])] = "100"
    fake_cells[(3, header_index["左上坡m1"])] = "1.5"
    fake_cells[(3, header_index["平台宽B1(m)"])] = "2.0"
    fake_cells[(3, header_index["左下坡m2"])] = "1.0"
    fake_cells[(3, header_index["渠底宽B2(m)"])] = "3.0"
    fake_cells[(3, header_index["右坡m3"])] = "1.0"
    fake_cells[(3, header_index["平台高差h1(m)"])] = "1.0"

    class _Cell:
        def __init__(self, value):
            self.value = value

    class _Sheet:
        max_row = 3

        def cell(self, row, column):
            return _Cell(fake_cells.get((row, column)))

    class _Workbook:
        active = _Sheet()

    fake_openpyxl = types.ModuleType("openpyxl")
    fake_openpyxl.load_workbook = lambda *args, **kwargs: _Workbook()
    monkeypatch.setitem(sys.modules, "openpyxl", fake_openpyxl)

    panel._do_load_from_filepath("compound.xlsx", is_sample=False)
    _flush_events(4)

    assert panel.input_table.item(0, header_index["结构形式"] - 1).text() == "明渠-复式梯形"
    assert panel.input_table.item(0, header_index["左上坡m1"] - 1).text() == "1.5"
    assert panel.input_table.item(0, header_index["渠底宽B2(m)"] - 1).text() == "3.0"

    panel.close()
    panel.deleteLater()
    _flush_events(4)
