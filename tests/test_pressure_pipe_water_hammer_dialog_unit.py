# -*- coding: utf-8 -*-
"""基础水锤验算弹窗单元测试。"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "推求水面线") not in sys.path:
    sys.path.insert(0, str(ROOT / "推求水面线"))

from app_渠系计算前端.water_profile.water_profile_dialogs import PressurePipeConfigDialog  # noqa: E402
from 推求水面线.managers.pressure_pipe_manager import PressurePipeConfig, PressurePipeManager  # noqa: E402


def _get_qapp():
    """返回测试可复用的 QApplication。"""
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    """推动事件循环，确保控件状态刷新。"""
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _make_group():
    """构造最小可用的有压管道分组。"""
    rows = [
        SimpleNamespace(
            section_params={"D": 1.2},
            turn_radius=0.0,
            flow_section="1",
            water_level=101.25,
        ),
    ]
    return SimpleNamespace(
        name="",
        display_name="流量段1 第5行有压管道",
        storage_key="flow1-row5",
        identity="flow1-row5",
        group_mode="unnamed_row_segment",
        design_flow=1.52,
        diameter=1.2,
        material_key="钢管",
        ip_points=[{"x": 0.0, "y": 0.0}, {"x": 210.0, "y": 0.0}],
        rows=rows,
        row_indices=[4],
        target_row_index=4,
        upstream_row_index=3,
    )


def _make_manager(project_path: Path, group) -> PressurePipeManager:
    """创建带已有专项结果的管理器。"""
    manager = PressurePipeManager(str(project_path))
    cfg = PressurePipeConfig(
        name=group.display_name,
        Q=group.design_flow,
        D=group.diameter,
        material_key=group.material_key,
        pipe_velocity=1.34,
        plan_total_length=210.0,
    )
    manager.set_pipe_config(group.storage_key, cfg)
    return manager


def _read_float(widget) -> float:
    """把输入框文本安全转成浮点数。"""
    return float(str(widget.text() or "0").strip())


def test_dialog_prefills_and_persists_basic_water_hammer_inputs_and_results():
    """弹窗应能预填、验算、保存并在重开后恢复基础水锤数据。"""
    _get_qapp()
    case_dir = Path(tempfile.mkdtemp(prefix="wh_dialog_"))
    project_path = case_dir / "demo.qxproj"
    group = _make_group()

    try:
        manager = _make_manager(project_path, group)
        dialog = PressurePipeConfigDialog(pipe_groups=[group], manager=manager)
        dialog.show()
        _flush_events(6)

        widgets = dialog._card_widgets[group.storage_key]
        assert _read_float(widgets["water_hammer_length_edit"]) == pytest.approx(210.0)
        assert _read_float(widgets["water_hammer_velocity_edit"]) == pytest.approx(1.34)
        assert _read_float(widgets["water_hammer_head_edit"]) == pytest.approx(101.25)
        assert _read_float(widgets["water_hammer_elastic_modulus_edit"]) > 0

        widgets["water_hammer_wall_thickness_edit"].setText("0.016")
        widgets["water_hammer_head_edit"].setText("102.4")
        widgets["water_hammer_closing_time_edit"].setText("0.25")
        QTest.mouseClick(widgets["water_hammer_calc_btn"], Qt.LeftButton)
        _flush_events(6)

        assert "可计算" in widgets["water_hammer_status_label"].text()
        assert widgets["water_hammer_result_hmax_label"].text() != "-"

        dialog.accept()
        _flush_events(2)

        reloaded_manager = PressurePipeManager(str(project_path))
        loaded = reloaded_manager.get_pipe_config(group.storage_key)
        assert loaded is not None
        assert loaded.wall_thickness_m == pytest.approx(0.016)
        assert loaded.water_hammer_basic["status"] == "可计算"
        assert loaded.water_hammer_basic["inputs"]["closing_time_s"] == pytest.approx(0.25)

        dialog_reopen = PressurePipeConfigDialog(pipe_groups=[group], manager=reloaded_manager)
        dialog_reopen.show()
        _flush_events(6)

        widgets_reopen = dialog_reopen._card_widgets[group.storage_key]
        assert _read_float(widgets_reopen["water_hammer_wall_thickness_edit"]) == pytest.approx(0.016)
        assert _read_float(widgets_reopen["water_hammer_head_edit"]) == pytest.approx(102.4)
        assert _read_float(widgets_reopen["water_hammer_closing_time_edit"]) == pytest.approx(0.25)
        assert "可计算" in widgets_reopen["water_hammer_status_label"].text()
        assert widgets_reopen["water_hammer_result_hmax_label"].text() != "-"

        dialog.close()
        dialog_reopen.close()
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
