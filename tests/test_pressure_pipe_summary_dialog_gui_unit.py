"""有压管道结果汇总窗生命周期 GUI 回归测试。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

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
            if "关闭并将总水头损失返回至水面线计算表格" in button.text()
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
