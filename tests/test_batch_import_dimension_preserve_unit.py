# -*- coding: utf-8 -*-
"""Regression coverage for preserving explicit open-channel bottom widths in batch mode."""

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

from app_渠系计算前端.batch.panel import BatchPanel, INPUT_HEADERS
import app_渠系计算前端.batch.panel as batch_panel_mod


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _build_row(*, q="1", slope_inv="2.2", b="1.5"):
    row = [""] * len(INPUT_HEADERS)
    row[0] = "1"
    row[1] = "1"
    row[2] = "-"
    row[3] = "明渠-矩形"
    row[6] = q
    row[7] = "0.014"
    row[8] = slope_inv
    row[9] = "0"
    row[10] = b
    row[18] = "0.1"
    row[19] = "100"
    return row


def _build_rect_aqueduct_row(*, q="1", slope_inv="2000", b="1.5", ratio="0.8", tie_rod_height=""):
    row = [""] * len(INPUT_HEADERS)
    row[0] = "1"
    row[1] = "1"
    row[2] = "测试渡槽"
    row[3] = "渡槽-矩形"
    row[6] = q
    row[7] = "0.014"
    row[8] = slope_inv
    row[10] = b
    row[14] = ratio
    row[18] = "0.1"
    row[19] = "100"
    if tie_rod_height != "":
        row[batch_panel_mod.COL_TIE_ROD_HEIGHT] = tie_rod_height
    return row


def _build_u_aqueduct_row(*, q="1", slope_inv="2000", radius="1.5", tie_rod_height=""):
    row = [""] * len(INPUT_HEADERS)
    row[0] = "1"
    row[1] = "1"
    row[2] = "测试U形渡槽"
    row[3] = "渡槽-U形"
    row[6] = q
    row[7] = "0.014"
    row[8] = slope_inv
    row[12] = radius
    row[18] = "0.1"
    row[19] = "100"
    if tie_rod_height != "":
        row[batch_panel_mod.COL_TIE_ROD_HEIGHT] = tie_rod_height
    return row


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


def _install_fake_openpyxl(monkeypatch, *, b_value="1.5"):
    cells = {
        (1, 1): "渠道名称",
        (1, 2): "测试渠道",
        (1, 3): "渠道级别",
        (1, 4): "支渠",
        (1, 5): "起始水位",
        (1, 6): "369.5",
        (1, 8): "0+000.000",
        (2, 5): "X",
        (2, 7): "Q(m3/s)",
        (3, 1): "1",
        (3, 2): "1",
        (3, 3): "-",
        (3, 4): "明渠-矩形",
        (3, 7): "1",
        (3, 8): "0.014",
        (3, 9): "2.2",
        (3, 10): "0",
        (3, 11): b_value,
        (3, 19): "0.1",
        (3, 20): "100",
    }

    class _Cell:
        def __init__(self, value):
            self.value = value

    class _Sheet:
        max_row = 3

        def cell(self, row, column):
            return _Cell(cells.get((row, column)))

    class _Workbook:
        active = _Sheet()

    fake_openpyxl = types.ModuleType("openpyxl")
    fake_openpyxl.load_workbook = lambda *args, **kwargs: _Workbook()
    monkeypatch.setitem(sys.modules, "openpyxl", fake_openpyxl)


def test_batch_calculate_preserves_explicit_bottom_width_and_registers_result(monkeypatch):
    registered_rows = []

    class _SharedManager:
        def clear_batch_results(self):
            return None

        def register_batch_results(self, rows):
            registered_rows.extend(rows)
            return len(rows)

    monkeypatch.setattr(batch_panel_mod, "SHARED_DATA_AVAILABLE", True)
    monkeypatch.setattr(batch_panel_mod, "get_shared_data_manager", lambda: _SharedManager())

    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_row())
    panel._set_excel_import_session_active(True)
    panel._mark_row_as_excel_imported(0, True)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    result = panel.batch_results[0]["result"]

    assert panel.result_table.item(0, 4).text() == "1.500"
    assert panel.result_table.item(0, status_col).text() == "⚠ 按显式底宽计算"
    assert result["preserved_manual_b"] is True
    assert result["used_manual_b"] is True
    assert any("宽深比" in warning for warning in result["constraint_warnings"])
    assert panel._has_calc_errors is False
    assert registered_rows
    assert registered_rows[0]["b_design"] == 1.5

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_batch_calculate_registers_explicit_zero_turn_radius_text(monkeypatch):
    registered_rows = []

    class _SharedManager:
        def clear_batch_results(self):
            return None

        def register_batch_results(self, rows):
            registered_rows.extend(rows)
            return len(rows)

    monkeypatch.setattr(batch_panel_mod, "SHARED_DATA_AVAILABLE", True)
    monkeypatch.setattr(batch_panel_mod, "get_shared_data_manager", lambda: _SharedManager())

    panel = _prepare_panel(monkeypatch)
    row = _build_row()
    row[20] = "0"
    _set_single_row(panel, row)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    assert registered_rows
    assert registered_rows[0]["turn_radius"] == 0.0
    assert registered_rows[0]["turn_radius_text"] == "0"

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_real_excel_import_marks_rows_as_imported(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    _install_fake_openpyxl(monkeypatch)

    panel._do_load_from_filepath("import.xlsx", is_sample=False)
    _flush_events(4)

    assert panel._excel_import_session_active is True
    assert panel._is_row_excel_imported(0) is True
    assert panel.input_table.item(0, 10).text() == "1.5"

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_sample_load_does_not_enable_excel_import_lock(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    _install_fake_openpyxl(monkeypatch)

    panel._do_load_from_filepath("sample.xlsx", is_sample=True)
    _flush_events(4)

    assert panel._excel_import_session_active is False
    assert panel._is_row_excel_imported(0) is False

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_batch_calculate_preserves_explicit_bottom_width_without_import_lock(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_row())
    panel._set_excel_import_session_active(False)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    result = panel.batch_results[0]["result"]

    assert panel.result_table.item(0, 4).text() == "1.500"
    assert panel.result_table.item(0, status_col).text() == "⚠ 按显式底宽计算"
    assert result["preserved_manual_b"] is True
    assert result["used_manual_b"] is True
    assert any("宽深比" in warning for warning in result["constraint_warnings"])

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_batch_calculate_without_explicit_bottom_width_keeps_appendix_e_auto_design(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_row(b=""))
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    result = panel.batch_results[0]["result"]

    assert panel.result_table.item(0, 4).text() == "0.429"
    assert panel.result_table.item(0, status_col).text() == "✓ 成功"
    assert result["preserved_manual_b"] is False
    assert result["used_manual_b"] is False

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_sample_load_preserves_explicit_bottom_width_during_batch_calculate(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    _install_fake_openpyxl(monkeypatch)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._do_load_from_filepath("sample.xlsx", is_sample=True)
    _flush_events(4)
    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    result = panel.batch_results[0]["result"]

    assert panel._excel_import_session_active is False
    assert panel._is_row_excel_imported(0) is False
    assert panel.result_table.item(0, 4).text() == "1.500"
    assert panel.result_table.item(0, status_col).text() == "⚠ 按显式底宽计算"
    assert result["preserved_manual_b"] is True
    assert result["used_manual_b"] is True

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_project_roundtrip_preserves_explicit_bottom_width_on_recalculate(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_row())
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    saved = panel.to_project_dict()

    restored = _prepare_panel(monkeypatch)
    restored.from_project_dict(saved, skip_dirty_signal=True)
    _flush_events(4)
    restored.inc_cb.setChecked(False)
    restored.detail_cb.setChecked(False)
    restored._batch_calculate()
    _flush_events(6)

    status_col = restored.result_table.columnCount() - 1
    result = restored.batch_results[0]["result"]

    assert restored._excel_import_session_active is False
    assert restored._is_row_excel_imported(0) is False
    assert restored.result_table.item(0, 4).text() == "1.500"
    assert restored.result_table.item(0, status_col).text() == "⚠ 按显式底宽计算"
    assert result["preserved_manual_b"] is True
    assert result["used_manual_b"] is True

    panel.close()
    panel.deleteLater()
    restored.close()
    restored.deleteLater()
    _flush_events(4)


def test_batch_calculate_import_lock_failure_disables_exports(monkeypatch):
    registered_rows = []

    class _SharedManager:
        def clear_batch_results(self):
            return None

        def register_batch_results(self, rows):
            registered_rows.extend(rows)
            return len(rows)

    monkeypatch.setattr(batch_panel_mod, "SHARED_DATA_AVAILABLE", True)
    monkeypatch.setattr(batch_panel_mod, "get_shared_data_manager", lambda: _SharedManager())

    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_row(q="1000", slope_inv="2000", b="0.01"))
    panel._set_excel_import_session_active(True)
    panel._mark_row_as_excel_imported(0, True)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    status_text = panel.result_table.item(0, status_col).text()

    assert panel._has_calc_errors is True
    assert "未自动改写" in status_text
    assert panel._btn_export_excel.isEnabled() is False
    assert panel._btn_export_word.isEnabled() is False
    assert registered_rows == []

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_rect_aqueduct_import_preserves_bottom_width_and_warns_on_ratio_conflict(monkeypatch):
    registered_rows = []
    captured_kwargs = []
    original_calc = batch_panel_mod.ducao_rect_calculate

    class _SharedManager:
        def clear_batch_results(self):
            return None

        def register_batch_results(self, rows):
            registered_rows.extend(rows)
            return len(rows)

    def _capture_calc(*args, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return original_calc(*args, **kwargs)

    monkeypatch.setattr(batch_panel_mod, "SHARED_DATA_AVAILABLE", True)
    monkeypatch.setattr(batch_panel_mod, "get_shared_data_manager", lambda: _SharedManager())
    monkeypatch.setattr(batch_panel_mod, "ducao_rect_calculate", _capture_calc)

    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_rect_aqueduct_row(ratio="0.8"))
    panel._set_excel_import_session_active(True)
    panel._mark_row_as_excel_imported(0, True)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    result = panel.batch_results[0]["result"]

    assert captured_kwargs
    assert captured_kwargs[0]["manual_B"] == 1.5
    assert panel.result_table.item(0, 4).text() == "1.500"
    assert panel.result_table.item(0, status_col).text() == "⚠ 按导入尺寸计算"
    assert result["B"] == 1.5
    assert result["preserved_manual_b"] is True
    assert result["used_manual_b"] is True
    assert result["imported_depth_width_ratio"] == 0.8
    assert any("H/B" in warning for warning in result["constraint_warnings"])
    assert panel._has_calc_errors is False
    assert panel._btn_export_excel.isEnabled() is True
    assert panel._btn_export_word.isEnabled() is True
    assert registered_rows
    assert registered_rows[0]["B"] == 1.5

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_u_aqueduct_batch_passes_tie_rod_height(monkeypatch):
    captured_kwargs = []
    original_calc = batch_panel_mod.ducao_u_calculate

    def _capture_calc(*args, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return original_calc(*args, **kwargs)

    monkeypatch.setattr(batch_panel_mod, "ducao_u_calculate", _capture_calc)

    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_u_aqueduct_row(tie_rod_height="0.30"))
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    result = panel.batch_results[0]["result"]

    assert captured_kwargs
    assert captured_kwargs[0]["tie_rod_height"] == pytest.approx(0.30)
    assert result["tie_rod_height"] == pytest.approx(0.30)
    assert result["H_total"] == pytest.approx(result["tie_bottom_height"] + 0.30)
    assert result["Fb"] == pytest.approx(result["tie_bottom_height"] - result["h_increased"])

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_u_aqueduct_batch_detail_report_handles_tie_rod_height(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    row = _build_u_aqueduct_row(q="5.0", slope_inv="3000", radius="2.4", tie_rod_height="0.30")
    result = panel._calculate_single(
        "渡槽-U形",
        Q=5.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        R=2.4,
        tie_rod_height=0.30,
        manual_increase_percent=0,
    )

    report = panel._gen_detail_report(row, result)

    assert "生成详细报告时出错" not in report
    assert "设计拉杆底净距" in report

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_batch_result_hides_effective_freeboard_when_increase_disabled(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_rect_aqueduct_row(ratio="", tie_rod_height="0.25"))
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    fb_col = batch_panel_mod.RESULT_HEADERS.index("加大有效超高Fb(m)")

    assert panel.result_table.item(0, fb_col).text() == "—"

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_batch_detail_report_hides_increase_section_when_disabled(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    row = _build_rect_aqueduct_row(ratio="", tie_rod_height="0.25")
    result = panel._calculate_single(
        "渡槽-矩形",
        Q=1.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        b=1.5,
        tie_rod_height=0.25,
        manual_increase_percent=0,
        preserve_imported_dimensions=True,
    )
    result["_use_increase"] = False

    report = panel._gen_detail_report(row, result)

    assert "加大流量工况" not in report
    assert "加大有效超高" not in report
    assert "设计拉杆底净距" in report

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_rect_aqueduct_batch_passes_tie_rod_height(monkeypatch):
    captured_kwargs = []
    original_calc = batch_panel_mod.ducao_rect_calculate

    def _capture_calc(*args, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return original_calc(*args, **kwargs)

    monkeypatch.setattr(batch_panel_mod, "ducao_rect_calculate", _capture_calc)

    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_rect_aqueduct_row(ratio="", tie_rod_height="0.25"))
    panel._set_excel_import_session_active(True)
    panel._mark_row_as_excel_imported(0, True)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    result = panel.batch_results[0]["result"]

    assert captured_kwargs
    assert captured_kwargs[0]["tie_rod_height"] == pytest.approx(0.25)
    assert result["tie_rod_height"] == pytest.approx(0.25)
    assert result["H_total"] == pytest.approx(result["tie_bottom_height"] + 0.25)
    assert result["Fb"] == pytest.approx(result["tie_bottom_height"] - result["h_increased"])

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_rect_aqueduct_import_preserves_bottom_width_without_warning_when_ratio_missing(monkeypatch):
    captured_kwargs = []
    original_calc = batch_panel_mod.ducao_rect_calculate

    def _capture_calc(*args, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return original_calc(*args, **kwargs)

    monkeypatch.setattr(batch_panel_mod, "ducao_rect_calculate", _capture_calc)

    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_rect_aqueduct_row(ratio=""))
    panel._set_excel_import_session_active(True)
    panel._mark_row_as_excel_imported(0, True)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    result = panel.batch_results[0]["result"]

    assert captured_kwargs
    assert captured_kwargs[0]["manual_B"] == 1.5
    assert panel.result_table.item(0, 4).text() == "1.500"
    assert panel.result_table.item(0, status_col).text() == "✓ 成功"
    assert result["preserved_manual_b"] is True
    assert result["used_manual_b"] is True
    assert result.get("imported_depth_width_ratio") is None
    assert result["constraint_warnings"] == []

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_rect_aqueduct_import_ratio_within_tolerance_keeps_success_status(monkeypatch):
    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_rect_aqueduct_row(ratio="0.61"))
    panel._set_excel_import_session_active(True)
    panel._mark_row_as_excel_imported(0, True)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    result = panel.batch_results[0]["result"]

    assert panel.result_table.item(0, 4).text() == "1.500"
    assert panel.result_table.item(0, status_col).text() == "✓ 成功"
    assert result["preserved_manual_b"] is True
    assert result["used_manual_b"] is True
    assert result["constraint_warnings"] == []

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_rect_aqueduct_import_lock_failure_disables_exports(monkeypatch):
    registered_rows = []
    captured_kwargs = []
    original_calc = batch_panel_mod.ducao_rect_calculate

    class _SharedManager:
        def clear_batch_results(self):
            return None

        def register_batch_results(self, rows):
            registered_rows.extend(rows)
            return len(rows)

    def _capture_calc(*args, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return original_calc(*args, **kwargs)

    monkeypatch.setattr(batch_panel_mod, "SHARED_DATA_AVAILABLE", True)
    monkeypatch.setattr(batch_panel_mod, "get_shared_data_manager", lambda: _SharedManager())
    monkeypatch.setattr(batch_panel_mod, "ducao_rect_calculate", _capture_calc)

    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_rect_aqueduct_row(q="1000", b="0.01", ratio="0.8"))
    panel._set_excel_import_session_active(True)
    panel._mark_row_as_excel_imported(0, True)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    status_text = panel.result_table.item(0, status_col).text()

    assert captured_kwargs
    assert captured_kwargs[0]["manual_B"] == 0.01
    assert panel._has_calc_errors is True
    assert "无法计算水深" in status_text
    assert panel._btn_export_excel.isEnabled() is False
    assert panel._btn_export_word.isEnabled() is False
    assert registered_rows == []

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_rect_aqueduct_without_import_lock_keeps_ratio_search_behavior(monkeypatch):
    captured_kwargs = []
    original_calc = batch_panel_mod.ducao_rect_calculate

    def _capture_calc(*args, **kwargs):
        captured_kwargs.append(dict(kwargs))
        return original_calc(*args, **kwargs)

    monkeypatch.setattr(batch_panel_mod, "ducao_rect_calculate", _capture_calc)

    panel = _prepare_panel(monkeypatch)
    _set_single_row(panel, _build_rect_aqueduct_row(ratio="0.8"))
    panel._set_excel_import_session_active(False)
    panel.inc_cb.setChecked(False)
    panel.detail_cb.setChecked(False)

    panel._batch_calculate()
    _flush_events(6)

    status_col = panel.result_table.columnCount() - 1
    result = panel.batch_results[0]["result"]

    assert captured_kwargs
    assert captured_kwargs[0].get("manual_B") is None
    assert panel.result_table.item(0, 4).text() == "1.310"
    assert panel.result_table.item(0, status_col).text() == "✓ 成功"
    assert result.get("preserved_manual_b") in (None, False)

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_batch_excel_template_contains_tie_rod_height_header():
    from openpyxl import load_workbook

    template_path = ROOT / "data" / "多流量段批量计算_导入Excel（模板）.xlsx"
    workbook = load_workbook(template_path, read_only=True, data_only=True)
    worksheet = workbook.active

    header_values = []
    for row in worksheet.iter_rows(min_row=1, max_row=8, values_only=True):
        header_values.extend(str(value).strip() for value in row if value is not None)

    assert "拉杆高度(m)" in header_values
