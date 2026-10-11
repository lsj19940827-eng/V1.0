"""真实水面线控件的状态往返与后台任务结果归属。"""

import copy
import json
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEX_FORCE_QTEXTBROWSER", "1")

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication


def wait_until(app, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert predicate(), "后台任务未在限时内结束"


@pytest.fixture
def panel(monkeypatch):
    from app_渠系计算前端.water_profile import panel as module
    from app_渠系计算前端.batch.panel import BatchPanel
    from 推求水面线.models.data_models import ChannelNode
    from 推求水面线.models.enums import StructureType, InOutType
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(BatchPanel, "_load_user_prefs", lambda self: None)
    for name in ("warning", "error", "info", "success"):
        monkeypatch.setattr(module.InfoBar, name, lambda *args, **kwargs: None)
    value = module.WaterProfilePanel()
    value.design_flow_edit.setText("2.5")
    value.max_flow_edit.setText("3.0")
    value.start_wl_edit.setText("100")
    value.roughness_edit.setText("0.014")
    value._section_sync_ready = True
    value._transition_topology_prepared = True
    nodes = []
    for index in range(3):
        node = ChannelNode()
        node.flow_section = "1"
        node.structure_type = StructureType.from_string("明渠-梯形")
        node.in_out = InOutType.NORMAL
        node.x = index * 100.123456789
        node.y = 0
        node.flow = 2.5
        node.design_flow = 2.5
        node.roughness = 0.014
        node.slope_i = 0.0005
        node.water_depth = 1.234567890123
        node.structure_height = 2.4
        node.section_params.update({"b": 2.0, "B": 2.0, "m": 1.5})
        nodes.append(node)
    value._update_table_from_nodes_full(nodes)
    value._generate_detail_report = lambda *args: None
    value._show_calculation_completion_notice = lambda *args, **kwargs: None
    yield app, value
    value.cancel_calculation()
    value._batch_backend.cancel_calculation()
    wait_until(app, lambda: not value.is_calculation_running() and not value._batch_backend.is_calculation_running())
    value.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("action", ["complete", "edit", "cancel", "replace", "error"])
def test_async_only_applies_current_success(panel, monkeypatch, action):
    from 推求水面线.core import calculation_service
    app, value = panel
    started, release = threading.Event(), threading.Event()
    ui_thread = threading.get_ident()
    threads, applied, heartbeats, errors = [], [], [], []
    real = calculation_service.calculate_profile

    def delayed(nodes, settings, check):
        threads.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        if action == "error":
            raise ValueError("模拟计算失败")
        return real(nodes, settings, check)

    monkeypatch.setattr(calculation_service, "calculate_profile", delayed)
    original_apply = value._apply_calculation_result

    def record_apply(*args):
        applied.append(threading.get_ident())
        original_apply(*args)

    value._apply_calculation_result = record_apply
    value._show_calculation_error = errors.append
    value._btn_calc.setEnabled(True)
    value._btn_calc.click()
    try:
        wait_until(app, started.is_set)
        QTimer.singleShot(0, lambda: heartbeats.append(True))
        wait_until(app, lambda: bool(heartbeats))
        assert value.is_calculation_running()
        if action == "edit":
            value.start_wl_edit.setText("105")
        elif action == "cancel":
            value._btn_calc.click()
        elif action == "replace":
            value.from_project_dict({}, skip_dirty_signal=True)
    finally:
        release.set()
    wait_until(app, lambda: not value.is_calculation_running())
    assert threads == [threads[0]] and threads[0] != ui_thread
    if action == "complete":
        assert applied == [ui_thread]
        assert len(value.calculated_nodes) == 3
        assert value.calculated_nodes[0].water_level == pytest.approx(100)
        assert value._btn_calc.text() == "执行计算"
        assert not errors
    else:
        assert applied == []
        assert bool(errors) == (action == "error")


def test_new_table_state_is_authoritative_and_undo_preserves_all_metadata(panel):
    _app, value = panel
    first = value.node_table.item(0, 0)
    payload = first.data(Qt.UserRole)
    payload["example_source"] = {"原始值": 0.12345678901234}
    first.setData(Qt.UserRole, payload)
    value.node_table.item(0, 4).setData(Qt.UserRole, {"来源": "手工复核"})
    state = value._capture_profile_table_state().to_dict()
    saved = value.to_project_dict()
    saved["node_table_rows"][0][0] = "旧字段不应覆盖状态"
    value.from_project_dict(json.loads(json.dumps(saved)), skip_dirty_signal=True)
    assert value._capture_profile_table_state().to_dict() == state
    snapshot = value._snapshot_node_table()
    value.node_table.item(0, 4).setText("修改值")
    value._restore_node_table(snapshot)
    assert value._capture_profile_table_state().to_dict() == state


@pytest.mark.parametrize("source", ["live_table", "serialized_table"])
def test_legacy_auto_channel_role_keeps_its_meaning_after_state_migration(panel, source):
    """旧标量补段标记经采集或工程迁移后，仍须按自动补段参与计算。"""
    from 推求水面线.models.profile_state import ProfileTableState
    _app, value = panel
    if source == "live_table":
        value.node_table.item(0, 0).setData(Qt.UserRole, "auto_channel")
    else:
        raw = value._capture_profile_table_state().to_dict()
        raw["rows"][0]["cell_data"]["0"] = "auto_channel"
        value._apply_profile_table_state(ProfileTableState.from_dict(raw))
    assert value._build_nodes_from_table()[0].is_auto_inserted_channel
    payload = value.node_table.item(0, 0).data(Qt.UserRole)
    assert payload["_auto_channel"] is True
    assert payload["_profile_legacy_user_role"] == "auto_channel"
    saved = json.loads(json.dumps(value.to_project_dict()))
    value.from_project_dict(saved, skip_dirty_signal=True)
    assert value._build_nodes_from_table()[0].is_auto_inserted_channel


def test_complete_state_clears_metadata_missing_from_saved_table(panel):
    """表格已清除的 IP 隐藏编号不能在重开时被旧节点缓存重新补回。"""
    _app, value = panel
    value.nodes = value._build_nodes_from_table()
    value.nodes[0].ip_number = value.nodes[0].display_ip_number = 7
    value._update_table_from_nodes_full(value.nodes)
    value._updating_cells = True
    try:
        value.node_table.item(0, 4).setText("IP99")
        value.node_table.item(0, 4).setData(Qt.UserRole, None)
    finally:
        value._updating_cells = False
    saved = json.loads(json.dumps(value.to_project_dict()))
    assert "4" not in saved["table_state"]["rows"][0]["cell_data"]
    assert saved["nodes"][0]["ip_number"] == 7
    value.from_project_dict(saved, skip_dirty_signal=True)
    assert value.node_table.item(0, 4).data(Qt.UserRole) is None
    assert value._build_nodes_from_table()[0].ip_number == 99


@pytest.mark.parametrize("action", ["complete", "table3_changed", "cancel"])
def test_merged_batch_blocks_conflicting_actions_and_checks_table3(panel, monkeypatch, action):
    from app_渠系计算前端.batch import panel as batch_module
    app, value = panel
    backend = value._batch_backend
    values = [""] * len(batch_module.INPUT_HEADERS)
    for column, text in {batch_module.COL_SEQ: "1", batch_module.COL_SEGMENT: "1",
                         batch_module.COL_SECTION_TYPE: "明渠-梯形", batch_module.COL_Q: "2.5",
                         batch_module.COL_N: "0.014", batch_module.COL_SLOPE: "2000",
                         batch_module.COL_M: "1.5", batch_module.COL_B: "2"}.items():
        values[column] = text
    backend.input_table.setRowCount(1)
    for column, text in enumerate(values):
        backend.input_table.setItem(0, column, batch_module.QTableWidgetItem(text))
    started, release = threading.Event(), threading.Event()
    real = batch_module.BatchCalculationService.calculate
    synchronized = []
    monkeypatch.setattr(value, '_sync_to_water_profile_table', lambda: synchronized.append(True) or True)

    def delayed(service, request, token=None):
        started.set()
        assert release.wait(5)
        return real(service, request, token)

    monkeypatch.setattr(batch_module.BatchCalculationService, 'calculate', delayed)
    value._btn_section_calc.click()
    try:
        wait_until(app, started.is_set)
        assert not value.node_table.isEnabled()
        assert not value._btn_transition.isEnabled()
        assert not value._btn_siphon.isEnabled()
        if action == 'table3_changed':
            value.node_table.item(0, 1).setText('后台期间由其他入口修改')
        elif action == 'cancel':
            value._btn_section_calc.click()
    finally:
        release.set()
    wait_until(app, lambda: not backend.is_calculation_running())
    assert synchronized == ([True] if action == 'complete' else [])
    assert value.node_table.isEnabled()
    assert value._btn_section_calc.text() == '开始批量计算'


def test_bad_new_table_state_does_not_mutate_current_panel(panel):
    _app, value = panel
    before = value.to_project_dict()
    bad = copy.deepcopy(before)
    bad["ui_settings"]["channel_name"] = "不应写入"
    bad["table_state"]["column_count"] = -1
    with pytest.raises(ValueError):
        value.from_project_dict(bad, skip_dirty_signal=True)
    assert value.to_project_dict() == before


def test_embedded_batch_collection_failure_protects_saved_project(panel, tmp_path, monkeypatch):
    from app_渠系计算前端.project_manager import ProjectManager
    from PySide6.QtWidgets import QMessageBox
    _app, value = panel
    manager = ProjectManager()
    monkeypatch.setattr(manager, "_iter_project_panel_entries", lambda **kwargs: [("water_profile_panel", value, "水面线")])
    monkeypatch.setattr(manager, "_add_recent_project", lambda path: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    path = tmp_path / "原工程.qxproj"
    path.write_text('{"原内容": true}', encoding="utf-8")
    old_bytes = path.read_bytes()
    manager._current_path = str(path)
    manager.mark_dirty()

    def fail():
        raise RuntimeError("模拟表1序列化失败")

    monkeypatch.setattr(value._batch_backend, "to_project_dict", fail)
    assert not manager.save_project()
    assert manager.is_dirty
    assert path.read_bytes() == old_bytes
    manager.deleteLater()
