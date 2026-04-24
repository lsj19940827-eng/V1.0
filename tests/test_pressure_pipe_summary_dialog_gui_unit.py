"""有压管道结果汇总窗生命周期与长列表体验 GUI 回归测试。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget, QTabWidget, QTextEdit
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from qfluentwidgets import ComboBox, LineEdit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "calc_渠系计算算法内核") not in sys.path:
    sys.path.insert(0, str(ROOT / "calc_渠系计算算法内核"))

from app_渠系计算前端.water_profile.panel import WaterProfilePanel


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 6):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _close_summary_windows():
    for widget in list(QApplication.topLevelWidgets()):
        if widget.windowTitle() == "有压管道计算结果汇总（请确认是否应用）":
            if hasattr(widget, "_confirmed"):
                widget._confirmed = True
            widget.close()
            widget.deleteLater()


def _make_record(index: int, *, status: str = "success", writeback_enabled: bool = True):
    """构造有压管道汇总窗测试记录。"""
    ok = status == "success"
    return {
        "identity": f"flow1-row{index}",
        "storage_key": f"flow1-row{index}",
        "display_name": f"流量段1 第{index + 1}行有压管道",
        "flow_section": "1",
        "name": f"流量段1 第{index + 1}行有压管道",
        "status": status,
        "writeback_enabled": writeback_enabled,
        "group_mode": "unnamed_row_segment",
        "data_mode": "平面+纵断面（独立叠加）",
        "target_row_index": index,
        "upstream_row_index": index - 1,
        "friction_loss": 0.0486 if ok else None,
        "total_bend_loss": 0.0 if ok else None,
        "inlet_transition_loss": 0.0 if ok else None,
        "outlet_transition_loss": 0.0 if ok else None,
        "local_loss": 0.0 if ok else None,
        "total_head_loss": 0.0486 if ok else None,
        "total_length": 24.0 if ok else None,
        "pipe_velocity": 0.56 if ok else None,
        "calc_steps": f"第{index + 1}行计算过程",
        "error": "" if ok else "测试失败原因",
        "note": "链起点锚点，本行不写回" if not writeback_enabled else "",
    }


def _make_large_batch_data():
    """构造包含上百条记录和连续承压链的测试批次。"""
    records = [_make_record(i, writeback_enabled=i != 0) for i in range(132)]
    records[12] = _make_record(12, status="failed")
    chain_summary = {
        "flow_section": "1",
        "display_name": "连续承压链1",
        "chain_complete": False,
        "total_head_loss": None,
        "member_count": 132,
        "success_count": 131,
        "failed_count": 1,
        "member_results": [
            {
                "display_name": rec["display_name"],
                "structure_type": "有压管道",
                "status": rec["status"],
                "writeback_enabled": rec["writeback_enabled"],
                "total_head_loss": rec.get("total_head_loss"),
                "error": rec.get("error", ""),
            }
            for rec in records
        ],
    }
    return {
        "summary": {"total": 132, "success": 131, "failed": 1},
        "last_run_at": "2026-04-24 16:57:56",
        "records": records,
        "chain_summaries": [chain_summary],
    }


def _open_large_summary_dialog(panel):
    """打开长列表汇总窗并返回窗口与捕获的应用结果。"""
    batch_data = _make_large_batch_data()
    results_by_identity = {
        rec["identity"]: rec
        for rec in batch_data["records"]
        if rec["status"] == "success"
    }
    applied = []
    panel._apply_pressure_pipe_results = lambda results, data: applied.append(
        {"results": dict(results or {}), "data": dict(data or {})}
    )
    panel._show_pressure_pipe_calc_summary_dialog(batch_data, results_by_identity)
    _flush_events(12)
    return panel._pressure_pipe_summary_dialog, applied, results_by_identity


def _tab_names(tabs):
    """读取页签标题。"""
    return [tabs.tabText(i) for i in range(tabs.count())]


def test_pressure_pipe_summary_dialog_destroys_window_and_clears_panel_reference():
    _get_qapp()
    panel = WaterProfilePanel()
    panel.show()
    _flush_events(8)

    applied = []
    panel._apply_pressure_pipe_results = lambda results, data: applied.append(
        {"results": dict(results or {}), "data": dict(data or {})}
    )

    batch_data = {
        "summary": {"total": 1, "success": 1, "failed": 0},
        "records": [
            {
                "identity": "flow1-row1",
                "storage_key": "flow1-row1",
                "display_name": "测试有压管道",
                "flow_section": "1",
                "name": "测试有压管道",
                "status": "success",
                "writeback_enabled": True,
                "group_mode": "unnamed_row_segment",
                "data_mode": "平面模式",
                "target_row_index": 0,
                "upstream_row_index": -1,
                "friction_loss": 0.12,
                "total_bend_loss": 0.03,
                "inlet_transition_loss": 0.01,
                "outlet_transition_loss": 0.02,
                "local_loss": 0.03,
                "total_head_loss": 0.18,
                "total_length": 24.0,
                "pipe_velocity": 0.56,
                "calc_steps": "test",
            }
        ],
    }
    results_by_identity = {
        "flow1-row1": {
            "identity": "flow1-row1",
            "storage_key": "flow1-row1",
            "display_name": "测试有压管道",
            "status": "success",
            "writeback_enabled": True,
            "group_mode": "unnamed_row_segment",
            "target_row_index": 0,
            "total_head_loss": 0.18,
        }
    }

    try:
        panel._show_pressure_pipe_calc_summary_dialog(batch_data, results_by_identity)
        _flush_events(8)

        summary_dialog = getattr(panel, "_pressure_pipe_summary_dialog", None)
        assert summary_dialog is not None

        apply_button = next(
            button
            for button in summary_dialog.findChildren(QPushButton)
            if "应用全部成功结果" in button.text()
        )
        QTest.mouseClick(apply_button, Qt.LeftButton)
        _flush_events(12)

        assert len(applied) == 1
        assert getattr(panel, "_pressure_pipe_summary_dialog", None) is None
        assert not any(
            widget.windowTitle() == "有压管道计算结果汇总（请确认是否应用）"
            for widget in QApplication.topLevelWidgets()
        )
    finally:
        _close_summary_windows()
        panel.close()
        panel.deleteLater()
        _flush_events(6)


def test_pressure_pipe_summary_dialog_uses_tabs_and_gives_table_enough_height():
    _get_qapp()
    panel = WaterProfilePanel()
    panel.show()
    _flush_events(8)

    try:
        summary_dialog, _applied, _results = _open_large_summary_dialog(panel)
        tabs = summary_dialog.findChild(QTabWidget, "pressurePipeSummaryTabs")
        table = summary_dialog.findChild(QTableWidget, "pressurePipeSummaryTable")

        assert tabs is not None
        assert _tab_names(tabs) == ["结果汇总", "连续链总览", "计算详情"]
        assert table is not None
        row_height = table.rowHeight(0) or 1
        visible_rows = table.viewport().height() / row_height
        assert visible_rows >= 10
    finally:
        _close_summary_windows()
        panel.close()
        panel.deleteLater()
        _flush_events(6)


def test_pressure_pipe_summary_dialog_detail_button_and_double_click_switch_to_detail_tab():
    _get_qapp()
    panel = WaterProfilePanel()
    panel.show()
    _flush_events(8)

    try:
        summary_dialog, _applied, _results = _open_large_summary_dialog(panel)
        tabs = summary_dialog.findChild(QTabWidget, "pressurePipeSummaryTabs")
        table = summary_dialog.findChild(QTableWidget, "pressurePipeSummaryTable")
        detail_text = summary_dialog.findChild(QTextEdit, "pressurePipeSummaryDetailText")

        detail_button = table.cellWidget(5, 0)
        QTest.mouseClick(detail_button, Qt.LeftButton)
        _flush_events(8)

        assert tabs.tabText(tabs.currentIndex()) == "计算详情"
        assert "第6行有压管道" in detail_text.toPlainText()
        assert "第6行计算过程" in detail_text.toPlainText()

        tabs.setCurrentIndex(0)
        _flush_events(4)
        table.cellDoubleClicked.emit(8, 2)
        _flush_events(8)

        assert tabs.tabText(tabs.currentIndex()) == "计算详情"
        assert "第9行有压管道" in detail_text.toPlainText()
    finally:
        _close_summary_windows()
        panel.close()
        panel.deleteLater()
        _flush_events(6)


def test_pressure_pipe_summary_dialog_filters_only_view_and_apply_all_success_results():
    _get_qapp()
    panel = WaterProfilePanel()
    panel.show()
    _flush_events(8)

    try:
        summary_dialog, applied, results_by_identity = _open_large_summary_dialog(panel)
        table = summary_dialog.findChild(QTableWidget, "pressurePipeSummaryTable")
        search_edit = summary_dialog.findChild(LineEdit, "pressurePipeSummarySearchEdit")
        status_filter = summary_dialog.findChild(ComboBox, "pressurePipeSummaryStatusFilter")

        search_edit.setText("第10行")
        _flush_events(8)
        visible_rows = [row for row in range(table.rowCount()) if not table.isRowHidden(row)]
        assert visible_rows == [9]

        search_edit.clear()
        status_filter.setCurrentText("失败")
        _flush_events(8)
        visible_rows = [row for row in range(table.rowCount()) if not table.isRowHidden(row)]
        assert visible_rows == [12]

        apply_button = next(
            button
            for button in summary_dialog.findChildren(QPushButton)
            if "应用全部成功结果" in button.text()
        )
        QTest.mouseClick(apply_button, Qt.LeftButton)
        _flush_events(12)

        assert len(applied) == 1
        assert len(applied[0]["results"]) == len(results_by_identity)
        assert len(applied[0]["results"]) == 131
    finally:
        _close_summary_windows()
        panel.close()
        panel.deleteLater()
        _flush_events(6)
