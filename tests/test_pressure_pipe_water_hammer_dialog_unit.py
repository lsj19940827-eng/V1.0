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
from 推求水面线.models.enums import StructureType  # noqa: E402


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


def _make_route_group(
    key: str,
    row_index: int,
    structure_type: str = "有压管道",
    *,
    route_key: str = "flow1-route1",
    start_mc: float = 0.0,
    end_mc: float = 10.0,
    diameter: float = 1.0,
    design_flow: float = 1.0,
    material_key: str = "钢管",
    pipe_velocity: float = 1.0,
):
    """构造整线水锤测试用分组。"""
    row = SimpleNamespace(
        structure_type=StructureType.from_string(structure_type),
        section_params={"D": diameter, "pipe_material": material_key},
        flow=design_flow,
        water_level=100.0 + row_index,
    )
    group = SimpleNamespace(
        name=key,
        display_name=key,
        storage_key=key,
        identity=key,
        route_key=route_key,
        route_display_name="测试整线",
        route_start_row_index=0,
        route_end_row_index=99,
        route_start_mc=0.0,
        route_end_mc=100.0,
        structure_type=structure_type,
        rows=[row],
        row_indices=[row_index],
        target_row_index=row_index,
        upstream_row_index=max(row_index - 1, 0),
        segment_start_mc=start_mc,
        segment_end_mc=end_mc,
        group_mode="unnamed_row_segment",
        design_flow=design_flow,
        diameter=diameter,
        material_key=material_key,
        ip_points=[{"x": start_mc, "y": 0.0}, {"x": end_mc, "y": 0.0}],
        plan_total_length=max(0.0, end_mc - start_mc),
    )
    group.pipe_velocity = pipe_velocity
    return group


def _make_route_dialog(groups, manager=None):
    """创建整线模式弹窗并刷新事件。"""
    _get_qapp()
    dialog = PressurePipeConfigDialog(
        pipe_groups=groups,
        manager=manager,
        pressure_chains=[],
        xxpipe_route_mode=True,
    )
    dialog.show()
    _flush_events(6)
    return dialog


def _read_float(widget) -> float:
    """把输入框文本安全转成浮点数。"""
    return float(str(widget.text() or "0").strip())


def _set_route_profile_and_water_levels(dialog, groups, *, centerline_elevation: float, water_level: float):
    """给整线测试补入纵断面中心线和表3水位。"""
    route_key = "flow1-route1"
    start_mc = min(float(getattr(group, "segment_start_mc", 0.0)) for group in groups)
    end_mc = max(float(getattr(group, "segment_end_mc", 0.0)) for group in groups)
    dialog._longitudinal_data[route_key] = [
        {"chainage": start_mc, "elevation": centerline_elevation},
        {"chainage": end_mc, "elevation": centerline_elevation},
    ]
    for group in groups:
        for row in group.rows:
            row.water_level = water_level


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


def test_route_water_hammer_segments_split_at_tunnel_and_keep_pressure_runs_whole():
    """整线水锤段应按连续有压段生成，并被无压隧洞切断。"""
    groups = [
        _make_route_group("pipe-a", 0, "有压管道", start_mc=0.0, end_mc=10.0, pipe_velocity=0.8),
        _make_route_group("pipe-b", 1, "定向钻", start_mc=10.0, end_mc=30.0, pipe_velocity=1.2),
        _make_route_group("tunnel", 2, "隧洞-圆形", start_mc=30.0, end_mc=80.0),
        _make_route_group("pipe-c", 3, "有压管道", start_mc=80.0, end_mc=120.0, pipe_velocity=0.9),
        _make_route_group("pipe-d", 4, "顶管", start_mc=120.0, end_mc=150.0, pipe_velocity=1.6),
    ]

    dialog = _make_route_dialog(groups)
    try:
        segments = dialog._build_route_water_hammer_segments(dialog._route_contexts["flow1-route1"])

        assert [segment["segment_key"] for segment in segments] == [
            "flow1-route1::pipe-a::pipe-b",
            "flow1-route1::pipe-c::pipe-d",
        ]
        assert [segment["member_keys"] for segment in segments] == [
            ["pipe-a", "pipe-b"],
            ["pipe-c", "pipe-d"],
        ]
        assert [segment["length_m"] for segment in segments] == pytest.approx([30.0, 70.0])
    finally:
        dialog.close()


def test_route_water_hammer_mixed_params_keep_single_segment_and_pick_fastest_representative():
    """混合参数连续有压段不拆段，默认代表行取最大流速成员。"""
    groups = [
        _make_route_group(
            "pipe-a",
            0,
            "有压管道",
            start_mc=0.0,
            end_mc=10.0,
            diameter=0.8,
            design_flow=0.8,
            material_key="HDPE管",
            pipe_velocity=0.9,
        ),
        _make_route_group(
            "pipe-b",
            1,
            "有压管道",
            start_mc=10.0,
            end_mc=25.0,
            diameter=0.5,
            design_flow=0.8,
            material_key="钢管",
            pipe_velocity=1.7,
        ),
    ]

    dialog = _make_route_dialog(groups)
    try:
        segments = dialog._build_route_water_hammer_segments(dialog._route_contexts["flow1-route1"])

        assert len(segments) == 1
        segment = segments[0]
        assert segment["mixed_params"] is True
        assert segment["selected_representative_key"] == "pipe-b"
        assert segment["inputs"]["diameter_m"] == pytest.approx(0.5)
        assert segment["inputs"]["velocity_mps"] == pytest.approx(1.7)
        assert "D" in segment["param_summary"]
        assert "管材" in segment["param_summary"]
    finally:
        dialog.close()


def test_route_only_dialog_shows_water_hammer_segment_panel_without_child_pipe_cards():
    """route-only 模式下整线卡应直接显示水锤段入口。"""
    groups = [
        _make_route_group("pipe-a", 0, "有压管道", start_mc=0.0, end_mc=10.0),
        _make_route_group("pipe-b", 1, "有压管道", start_mc=10.0, end_mc=20.0),
    ]

    dialog = _make_route_dialog(groups)
    try:
        route_refs = dialog._route_widgets["flow1-route1"]
        segment_widgets = route_refs["water_hammer_segment_widgets"]

        assert dialog._card_widgets == {}
        assert len(segment_widgets) == 1
        assert segment_widgets[0]["segment_key"] == "flow1-route1::pipe-a::pipe-b"
        assert segment_widgets[0]["water_hammer_calc_btn"].text() == "验算/刷新"
    finally:
        dialog.close()


def test_route_water_hammer_bulk_inputs_apply_all_and_same_material_only():
    """整线水锤段应支持批量填写全部段和同管材段。"""
    groups = [
        _make_route_group("pipe-a", 0, "有压管道", start_mc=0.0, end_mc=10.0, material_key="钢管"),
        _make_route_group("tunnel-a", 1, "隧洞-圆形", start_mc=10.0, end_mc=20.0),
        _make_route_group("pipe-b", 2, "有压管道", start_mc=20.0, end_mc=30.0, material_key="HDPE管"),
        _make_route_group("tunnel-b", 3, "隧洞-圆形", start_mc=30.0, end_mc=40.0),
        _make_route_group("pipe-c", 4, "有压管道", start_mc=40.0, end_mc=50.0, material_key="钢管"),
    ]

    dialog = _make_route_dialog(groups)
    try:
        route_refs = dialog._route_widgets["flow1-route1"]
        segment_widgets = route_refs["water_hammer_segment_widgets"]
        assert len(segment_widgets) == 3

        route_refs["water_hammer_bulk_e_edit"].setText("0.011")
        route_refs["water_hammer_bulk_ts_edit"].setText("0.02")
        QTest.mouseClick(route_refs["water_hammer_bulk_all_btn"], Qt.LeftButton)
        _flush_events(4)

        for widgets in segment_widgets:
            assert _read_float(widgets["water_hammer_wall_thickness_edit"]) == pytest.approx(0.011)
            assert _read_float(widgets["water_hammer_closing_time_edit"]) == pytest.approx(0.02)

        segment_widgets[1]["water_hammer_wall_thickness_edit"].setText("0.017")
        segment_widgets[1]["water_hammer_closing_time_edit"].setText("0.05")
        route_refs["water_hammer_bulk_e_edit"].setText("0.022")
        route_refs["water_hammer_bulk_ts_edit"].setText("0.03")
        QTest.mouseClick(route_refs["water_hammer_bulk_same_material_btn"], Qt.LeftButton)
        _flush_events(4)

        assert _read_float(segment_widgets[0]["water_hammer_wall_thickness_edit"]) == pytest.approx(0.022)
        assert _read_float(segment_widgets[0]["water_hammer_closing_time_edit"]) == pytest.approx(0.03)
        assert _read_float(segment_widgets[1]["water_hammer_wall_thickness_edit"]) == pytest.approx(0.017)
        assert _read_float(segment_widgets[1]["water_hammer_closing_time_edit"]) == pytest.approx(0.05)
        assert _read_float(segment_widgets[2]["water_hammer_wall_thickness_edit"]) == pytest.approx(0.022)
        assert _read_float(segment_widgets[2]["water_hammer_closing_time_edit"]) == pytest.approx(0.03)
    finally:
        dialog.close()


def test_route_water_hammer_calculation_does_not_mutate_table3_loss_chain_fields():
    """整线水锤验算只做独立校核，不改表3损失和水位字段。"""
    groups = [
        _make_route_group("pipe-a", 0, "有压管道", start_mc=0.0, end_mc=10.0),
        _make_route_group("pipe-b", 1, "有压管道", start_mc=10.0, end_mc=20.0),
    ]
    for idx, group in enumerate(groups):
        row = group.rows[0]
        row.head_loss_total = 1.0 + idx
        row.head_loss_cumulative = 2.0 + idx
        row.water_level = 100.0 + idx
        row.pressure_pipe_window_override = {"total_head_loss": 9.9}
    before = [
        (
            group.rows[0].head_loss_total,
            group.rows[0].head_loss_cumulative,
            group.rows[0].water_level,
            dict(group.rows[0].pressure_pipe_window_override),
        )
        for group in groups
    ]

    dialog = _make_route_dialog(groups)
    try:
        widgets = dialog._route_widgets["flow1-route1"]["water_hammer_segment_widgets"][0]
        widgets["water_hammer_wall_thickness_edit"].setText("0.012")
        widgets["water_hammer_closing_time_edit"].setText("0.01")
        QTest.mouseClick(widgets["water_hammer_calc_btn"], Qt.LeftButton)
        _flush_events(6)

        after = [
            (
                group.rows[0].head_loss_total,
                group.rows[0].head_loss_cumulative,
                group.rows[0].water_level,
                dict(group.rows[0].pressure_pipe_window_override),
            )
            for group in groups
        ]
        assert after == before
    finally:
        dialog.close()


def test_route_water_hammer_distribution_check_shows_pass_and_detail_rows():
    """整线水锤验算应按管顶余量判定通过并展示全线采样明细。"""
    groups = [
        _make_route_group("pipe-a", 0, "有压管道", start_mc=0.0, end_mc=10.0, diameter=1.0),
        _make_route_group("pipe-b", 1, "有压管道", start_mc=10.0, end_mc=20.0, diameter=0.5, pipe_velocity=2.0),
    ]

    dialog = _make_route_dialog(groups)
    try:
        _set_route_profile_and_water_levels(dialog, groups, centerline_elevation=100.0, water_level=400.0)
        widgets = dialog._route_widgets["flow1-route1"]["water_hammer_segment_widgets"][0]
        widgets["water_hammer_wall_thickness_edit"].setText("0.02")
        widgets["water_hammer_closing_time_edit"].setText("0.01")
        QTest.mouseClick(widgets["water_hammer_calc_btn"], Qt.LeftButton)
        _flush_events(6)

        assert "通过" in widgets["water_hammer_status_label"].text()
        assert widgets["water_hammer_result_conclusion_label"].text() == "通过"
        assert widgets["water_hammer_result_exceed_count_label"].text() == "0"
        assert _read_float(widgets["water_hammer_result_min_margin_label"]) > 0

        assert widgets["water_hammer_detail_table"].isVisible() is False
        QTest.mouseClick(widgets["water_hammer_detail_btn"], Qt.LeftButton)
        _flush_events(4)
        assert widgets["water_hammer_detail_table"].isVisible() is True
        assert widgets["water_hammer_detail_table"].rowCount() >= 21
        assert widgets["water_hammer_detail_table"].horizontalHeaderItem(2).text() == "表3水位(m)"
    finally:
        dialog.close()


def test_route_water_hammer_distribution_check_marks_failed_when_margin_negative():
    """整线任一采样点余量为负时应显示不通过。"""
    groups = [
        _make_route_group("pipe-a", 0, "有压管道", start_mc=0.0, end_mc=10.0, diameter=1.0),
    ]

    dialog = _make_route_dialog(groups)
    try:
        _set_route_profile_and_water_levels(dialog, groups, centerline_elevation=100.0, water_level=120.0)
        widgets = dialog._route_widgets["flow1-route1"]["water_hammer_segment_widgets"][0]
        widgets["water_hammer_wall_thickness_edit"].setText("0.02")
        widgets["water_hammer_closing_time_edit"].setText("0.01")
        QTest.mouseClick(widgets["water_hammer_calc_btn"], Qt.LeftButton)
        _flush_events(6)

        assert "不通过" in widgets["water_hammer_status_label"].text()
        assert widgets["water_hammer_result_conclusion_label"].text() == "不通过"
        assert int(widgets["water_hammer_result_exceed_count_label"].text()) > 0
        assert _read_float(widgets["water_hammer_result_min_margin_label"]) < 0
    finally:
        dialog.close()


def test_route_water_hammer_distribution_ignores_manual_representative_d_e_v_edits():
    """整线分布正式判定应使用成员自身参数，避免手填代表值误导全段。"""
    groups = [
        _make_route_group("pipe-a", 0, "有压管道", start_mc=0.0, end_mc=10.0, diameter=1.0, pipe_velocity=1.0),
    ]

    dialog = _make_route_dialog(groups)
    try:
        _set_route_profile_and_water_levels(dialog, groups, centerline_elevation=100.0, water_level=130.0)
        widgets = dialog._route_widgets["flow1-route1"]["water_hammer_segment_widgets"][0]
        widgets["water_hammer_diameter_edit"].setText("0.1")
        widgets["water_hammer_velocity_edit"].setText("0.01")
        widgets["water_hammer_elastic_modulus_edit"].setText("1e12")
        widgets["water_hammer_wall_thickness_edit"].setText("0.02")
        widgets["water_hammer_closing_time_edit"].setText("0.01")
        QTest.mouseClick(widgets["water_hammer_calc_btn"], Qt.LeftButton)
        _flush_events(6)

        assert "不通过" in widgets["water_hammer_status_label"].text()
        assert widgets["water_hammer_diameter_edit"].isReadOnly()
        assert widgets["water_hammer_velocity_edit"].isReadOnly()
        assert widgets["water_hammer_elastic_modulus_edit"].isReadOnly()
    finally:
        dialog.close()


def test_route_water_hammer_segments_persist_and_restore_from_manager():
    """route 级水锤结果应随项目保存并在重开弹窗后恢复。"""
    case_dir = Path(tempfile.mkdtemp(prefix="wh_route_"))
    project_path = case_dir / "demo.qxproj"
    groups = [
        _make_route_group("pipe-a", 0, "有压管道", start_mc=0.0, end_mc=10.0),
        _make_route_group("pipe-b", 1, "有压管道", start_mc=10.0, end_mc=20.0),
    ]

    try:
        manager = PressurePipeManager(str(project_path))
        dialog = _make_route_dialog(groups, manager=manager)
        _set_route_profile_and_water_levels(dialog, groups, centerline_elevation=100.0, water_level=400.0)
        route_refs = dialog._route_widgets["flow1-route1"]
        widgets = route_refs["water_hammer_segment_widgets"][0]
        widgets["water_hammer_wall_thickness_edit"].setText("0.02")
        widgets["water_hammer_closing_time_edit"].setText("0.01")
        QTest.mouseClick(widgets["water_hammer_calc_btn"], Qt.LeftButton)
        _flush_events(6)
        dialog._persist_route_water_hammer_segments()
        _flush_events(2)

        reloaded_manager = PressurePipeManager(str(project_path))
        snapshot = reloaded_manager.get_route_config("flow1-route1")
        assert snapshot["water_hammer_segments"][0]["segment_key"] == "flow1-route1::pipe-a::pipe-b"
        assert snapshot["water_hammer_segments"][0]["inputs"]["wall_thickness_m"] == pytest.approx(0.02)
        assert snapshot["water_hammer_segments"][0]["inputs"]["closing_time_s"] == pytest.approx(0.01)
        assert snapshot["water_hammer_segments"][0]["result"]["status"] == "通过"
        assert snapshot["water_hammer_segments"][0]["result"]["details"] == []
        assert snapshot["water_hammer_segments"][0]["result"]["sample_count"] > 0

        dialog_reopen = _make_route_dialog(groups, manager=reloaded_manager)
        widgets_reopen = dialog_reopen._route_widgets["flow1-route1"]["water_hammer_segment_widgets"][0]
        assert _read_float(widgets_reopen["water_hammer_wall_thickness_edit"]) == pytest.approx(0.02)
        assert _read_float(widgets_reopen["water_hammer_closing_time_edit"]) == pytest.approx(0.01)
        assert "通过" in widgets_reopen["water_hammer_status_label"].text()
        dialog_reopen.close()
    finally:
        try:
            dialog.close()
        except Exception:
            pass
        shutil.rmtree(case_dir, ignore_errors=True)
