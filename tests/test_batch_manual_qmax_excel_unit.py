# -*- coding: utf-8 -*-
"""批量页 Excel 手工 Q加大 入口的回归测试。"""

import os
import sys
import tempfile
import types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from app_渠系计算前端.batch.panel import (
    BatchPanel,
    INPUT_HEADERS,
    format_manual_qmax_label,
    read_manual_qmax_map_from_sheet,
)
import app_渠系计算前端.batch.panel as batch_panel_mod


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _build_row(*, seq="1", segment="1", name="-", q="5", slope_inv="2000", b="1.5"):
    row = [""] * len(INPUT_HEADERS)
    row[0] = seq
    row[1] = segment
    row[2] = name
    row[3] = "明渠-矩形"
    row[6] = q
    row[7] = "0.014"
    row[8] = slope_inv
    row[9] = "0"
    row[10] = b
    row[18] = "0.1"
    row[19] = "100"
    return row


def _prepare_panel(monkeypatch, success_calls=None):
    _get_qapp()

    class _InfoBarStub:
        @staticmethod
        def success(*args, **kwargs):
            if success_calls is not None:
                success_calls.append((args, kwargs))
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

    panel = BatchPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)
    panel._clear_input(force=True)
    _flush_events(2)
    return panel


def _set_single_row(panel, row_data):
    panel._add_row(row_data)
    panel._renumber()
    _flush_events(2)


class _Cell:
    def __init__(self, value):
        self.value = value


class _Sheet:
    def __init__(self, cells, *, max_row, max_column):
        self._cells = dict(cells)
        self.max_row = max_row
        self.max_column = max_column

    def cell(self, row, column):
        return _Cell(self._cells.get((row, column)))


class _Workbook:
    def __init__(self, sheet):
        self.active = sheet


def _install_fake_openpyxl(monkeypatch, workbook):
    fake_openpyxl = types.ModuleType("openpyxl")
    fake_openpyxl.load_workbook = lambda *args, **kwargs: workbook
    monkeypatch.setitem(sys.modules, "openpyxl", fake_openpyxl)


def _build_import_workbook(*, manual_qmax_by_segment=None, rows=None):
    manual_qmax_by_segment = manual_qmax_by_segment or {}
    rows = rows or []
    cells = {
        (1, 1): "渠道名称",
        (1, 2): "测试渠道",
        (1, 3): "渠道级别",
        (1, 4): "支渠",
        (1, 5): "渠道起始水位高程(m)",
        (1, 6): "369.5",
        (1, 7): "起始桩号",
        (1, 8): "0+000.000",
        (2, 5): "X",
        (2, 7): "Q(m3/s)",
    }

    max_column = 20
    for segment_index in range(1, max(manual_qmax_by_segment.keys(), default=0) + 1):
        label_col = 9 + (segment_index - 1) * 2
        value_col = label_col + 1
        cells[(1, label_col)] = format_manual_qmax_label(segment_index)
        if segment_index in manual_qmax_by_segment:
            cells[(1, value_col)] = manual_qmax_by_segment[segment_index]
        max_column = max(max_column, value_col)

    for row_offset, row_data in enumerate(rows, start=3):
        for col_idx, value in enumerate(row_data, start=1):
            if value != "":
                cells[(row_offset, col_idx)] = value
                max_column = max(max_column, col_idx)

    sheet = _Sheet(cells, max_row=max(2, len(rows) + 2), max_column=max_column)
    return _Workbook(sheet)


def test_read_manual_qmax_map_preserves_blank_pairs_and_supports_extension():
    cells = {
        (1, 9): format_manual_qmax_label(1),
        (1, 10): "5.5",
        (1, 11): format_manual_qmax_label(2),
        (1, 13): format_manual_qmax_label(3),
        (1, 14): 7.25,
        (1, 49): format_manual_qmax_label(21),
        (1, 50): "30.2",
    }
    sheet = _Sheet(cells, max_row=3, max_column=50)

    result = read_manual_qmax_map_from_sheet(sheet, info_row=1)

    assert result == {1: 5.5, 3: 7.25, 21: 30.2}


def test_excel_import_reads_manual_qmax_and_batch_uses_segment_specific_values(monkeypatch):
    success_calls = []
    panel = _prepare_panel(monkeypatch, success_calls=success_calls)
    workbook = _build_import_workbook(
        manual_qmax_by_segment={1: 5.5},
        rows=[
            _build_row(seq="1", segment="1", name="一号渠段"),
            _build_row(seq="2", segment="2", name="二号渠段"),
        ],
    )
    _install_fake_openpyxl(monkeypatch, workbook)

    panel._do_load_from_filepath("import.xlsx", is_sample=False)
    _flush_events(4)
    panel.inc_cb.setChecked(True)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    assert panel._manual_qmax_by_segment == {1: 5.5}
    assert panel.batch_results[0]["result"]["Q_increased"] == pytest.approx(5.5)
    assert panel.batch_results[1]["result"]["Q_increased"] == pytest.approx(6.0)
    assert any(
        args[0] == "导入成功" and "已识别手工加大流量：第1段" in args[1]
        for args, _kwargs in success_calls
    )

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_batch_calculate_marks_error_when_manual_qmax_is_below_design_q(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_row(q="5"))
    panel._manual_qmax_by_segment = {1: 4.9}
    panel.inc_cb.setChecked(True)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    assert "不能小于设计流量 Q" in panel.result_table.item(0, status_col).text()
    assert panel.batch_results == []

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_project_roundtrip_preserves_manual_qmax_mapping(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_row(q="5"))
    panel._manual_qmax_by_segment = {1: 5.5, 3: 7.2}

    saved = panel.to_project_dict()

    restored = _prepare_panel(monkeypatch)
    restored.from_project_dict(saved, skip_dirty_signal=True)
    _flush_events(4)
    restored.inc_cb.setChecked(True)
    restored.detail_cb.setChecked(False)
    restored._batch_calculate()
    _flush_events(6)

    assert restored._manual_qmax_by_segment == {1: 5.5, 3: 7.2}
    assert restored.batch_results[0]["result"]["Q_increased"] == pytest.approx(5.5)

    panel.close()
    panel.deleteLater()
    restored.close()
    restored.deleteLater()
    _flush_events(4)
