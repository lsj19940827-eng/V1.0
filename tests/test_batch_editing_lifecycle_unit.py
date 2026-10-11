"""表1真实控件的批量编辑、撤销和下游失效回归。"""

import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('CODEX_FORCE_QTEXTBROWSER', '1')

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QTableWidgetItem, QTableWidgetSelectionRange

from app_渠系计算前端.batch import panel as module


@pytest.fixture
def panel(monkeypatch):
    app = QApplication.instance() or QApplication([])
    for name in ('success', 'warning', 'info', 'error'):
        monkeypatch.setattr(module.InfoBar, name, lambda *a, **k: None)
    monkeypatch.setattr(module, 'fluent_question', lambda *a, **k: True)
    monkeypatch.setattr(module, 'fluent_info', lambda *a, **k: None)
    value = module.BatchPanel()
    value._clear_input(force=True, clear_shared=False)
    value._table_undo_stack.clear()
    value._table_redo_stack.clear()
    yield value
    value.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def populate(panel, rows=3, section='明渠-梯形'):
    table = panel.input_table
    blocked = table.blockSignals(True)
    table.setRowCount(rows)
    for r in range(rows):
        for c in range(table.columnCount()):
            table.setItem(r, c, QTableWidgetItem(''))
        for c, val in {
            module.COL_SEQ: str(r+1), module.COL_SEGMENT: '1',
            module.COL_BUILDING_NAME: f'渠道{r+1}', module.COL_SECTION_TYPE: section,
            module.COL_Q: '1.23456789012345', module.COL_N: '0.014',
            module.COL_SLOPE: '3000', module.COL_M: '1.5',
        }.items():
            table.item(r, c).setText(val)
        panel._update_roughness_cell_state(r)
    table.blockSignals(blocked)
    table.setCurrentCell(0, module.COL_BUILDING_NAME)
    panel._table_undo_stack.clear()
    panel._table_redo_stack.clear()
    panel._remember_current_input_cell()


def paste(panel, text, row=0, col=0):
    panel.input_table.setCurrentCell(row, col)
    QApplication.clipboard().setText(text)
    panel._paste_from_clipboard()


def test_selection_does_not_copy_table_and_repeat_edits_have_individual_undo(panel, monkeypatch):
    populate(panel, 100)
    calls = []
    original = panel._snapshot_table
    monkeypatch.setattr(panel, '_snapshot_table', lambda: (calls.append(1), original())[1])
    for row in range(100):
        panel.input_table.setCurrentCell(row, module.COL_BUILDING_NAME)
    assert calls == []
    item = panel.input_table.item(99, module.COL_BUILDING_NAME)
    item.setText('修改一')
    item.setText('修改二')
    assert len(panel._table_undo_stack) == 2
    panel._undo_table()
    assert panel.input_table.item(99, module.COL_BUILDING_NAME).text() == '修改一'
    panel._undo_table()
    assert panel.input_table.item(99, module.COL_BUILDING_NAME).text() == '渠道100'
    panel._redo_table()
    assert panel.input_table.item(99, module.COL_BUILDING_NAME).text() == '修改一'


def test_paste_coalesces_signals_and_keeps_explicit_flow_precision(panel):
    populate(panel, 2)
    panel.flow_segments_edit.setText('5.0')
    signals = []
    panel.input_changed.connect(lambda: signals.append('input'))
    panel.data_changed.connect(lambda: signals.append('dirty'))
    rows = [f'{r+1}\t1\t节点{r+1}\t梯形\t\t\t1.23456789012345\t0.015\t' for r in range(80)]
    paste(panel, '\r\n'.join(rows)+'\r\n')
    assert signals == ['input', 'dirty']
    assert panel.input_table.rowCount() == 80
    assert len(panel._table_undo_stack) == 1
    assert panel.input_table.item(79, module.COL_Q).text() == '1.23456789012345'
    assert panel.input_table.item(79, module.COL_SECTION_TYPE).text() == '明渠-梯形'
    assert panel.input_table.item(79, module.COL_SLOPE).text() == '3000'
    panel._undo_table()
    assert panel.input_table.rowCount() == 2
    assert panel.flow_segments_edit.text() == '5.0'
    panel._redo_table()
    assert panel.input_table.rowCount() == 80
    assert len(signals) == 6


def test_paste_retains_leading_and_trailing_empty_cells(panel):
    populate(panel, 1)
    paste(panel, '\t新建筑物\t', col=module.COL_SEGMENT)
    assert panel.input_table.item(0, module.COL_SEGMENT).text() == ''
    assert panel.input_table.item(0, module.COL_BUILDING_NAME).text() == '新建筑物'
    assert panel.input_table.item(0, module.COL_SECTION_TYPE).text() == ''


@pytest.mark.parametrize('section', ['有压管道', '定向钻', '顶管'])
def test_pressure_paste_and_history_keep_roughness_readonly(panel, section):
    populate(panel, 1)
    paste(panel, f'1\t1\t管段\t{section}\t\t\t2.3\t0.014')
    assert not panel.input_table.item(0, module.COL_N).flags() & Qt.ItemIsEditable
    panel._undo_table()
    assert panel.input_table.item(0, module.COL_N).flags() & Qt.ItemIsEditable
    panel._redo_table()
    assert not panel.input_table.item(0, module.COL_N).flags() & Qt.ItemIsEditable


def test_segment_only_paste_syncs_flow_and_history_preserves_hidden_parameters(panel):
    populate(panel, 1)
    panel.flow_segments_edit.setText('1.2, 2.3456789012345')
    panel._set_rect_culvert_manual_h(0, 4.1234567890123)
    original = panel._snapshot_table()
    panel._table_undo_stack.clear()
    paste(panel, '2', col=module.COL_SEGMENT)
    assert panel.input_table.item(0, module.COL_Q).text() == '2.3456789012345'
    panel._undo_table()
    assert panel._snapshot_table() == original


def test_delete_and_fill_down_each_notify_once_and_have_one_undo(panel):
    populate(panel, 8)
    signals = []
    panel.input_changed.connect(lambda: signals.append(1))
    table = panel.input_table
    table.clearSelection()
    table.setRangeSelected(QTableWidgetSelectionRange(0, module.COL_BUILDING_NAME, 7, module.COL_BUILDING_NAME), True)
    original = panel._snapshot_table()
    table._delete_selected_cells()
    assert signals == [1]
    assert len(panel._table_undo_stack) == 1
    panel._undo_table()
    assert panel._snapshot_table() == original
    signals.clear()
    panel._table_undo_stack.clear()
    table.setRangeSelected(QTableWidgetSelectionRange(0, module.COL_BUILDING_NAME, 7, module.COL_BUILDING_NAME), True)
    panel._fill_down_input()
    assert signals == [1]
    assert len(panel._table_undo_stack) == 1
    assert table.item(7, module.COL_BUILDING_NAME).text() == '渠道1'


def test_deleting_last_row_notifies_and_undo_restores_it(panel):
    populate(panel, 1)
    signals = []
    panel.input_changed.connect(lambda: signals.append(1))
    panel.input_table.selectRow(0)
    panel._del_row()
    assert panel.input_table.rowCount() == 0
    assert signals == [1]
    panel._undo_table()
    assert panel.input_table.rowCount() == 1
    assert signals == [1, 1]


def test_paste_failure_restores_signal_and_redraw_state_and_can_be_undone(panel, monkeypatch):
    populate(panel, 1)
    original = panel._snapshot_table()
    monkeypatch.setattr(panel, '_auto_detect_flow_segments', lambda: (_ for _ in ()).throw(ValueError('模拟失败')))
    with pytest.raises(ValueError, match='模拟失败'):
        paste(panel, '新名称', col=module.COL_BUILDING_NAME)
    assert not panel.input_table.signalsBlocked()
    assert panel.input_table.updatesEnabled()
    assert panel._undo_group == 0
    panel._undo_table()
    assert panel._snapshot_table() == original


def test_undo_clear_restores_imported_dimension_policy_and_manual_increase(panel):
    populate(panel, 1, section='渡槽-矩形')
    panel._set_excel_import_session_active(True)
    panel._mark_row_as_excel_imported(0, True)
    panel._manual_qmax_by_segment = {1: 4.56789012345}
    original = panel._snapshot_table()
    panel._clear_input(force=True, clear_shared=False)
    panel._undo_table()
    assert panel._snapshot_table() == original
    assert panel._should_preserve_imported_dimensions(0, '渡槽-矩形', 2.3456789)


def test_type_dialog_notifies_after_defaults_and_hidden_parameters_are_committed(panel, monkeypatch):
    populate(panel, 1, section='暗涵-矩形')
    panel._set_rect_culvert_manual_h(0, 4.123456789)
    panel.input_table.setCurrentCell(0, module.COL_SECTION_TYPE)
    class Selector:
        selected_type = '明渠-梯形'
        def __init__(self, parent):
            pass
        def set_current(self, value):
            pass
        def exec(self):
            return module.QDialog.DialogCode.Accepted
    monkeypatch.setattr(module, 'StructureTypeSelector', Selector)
    states = []
    panel.input_changed.connect(lambda: states.append(panel._get_rect_culvert_manual_h(0)))
    panel._on_cell_double_clicked(0, module.COL_SECTION_TYPE)
    assert states == [None]
    panel._undo_table()
    assert states[-1] == 4.123456789
    panel._redo_table()
    assert states[-1] is None
    panel.input_table.item(0, module.COL_SECTION_TYPE).setText('有压管道')
    panel._undo_table()
    assert panel._get_rect_culvert_manual_h(0) is None


@pytest.mark.parametrize('action', ['paste', 'undo', 'redo', 'apply_flow', 'parameters', 'delete_last',
                                  'add', 'insert', 'copy', 'clear'])
def test_merged_input_operations_mark_project_dirty_and_invalidate_results(panel, action):
    from app_渠系计算前端.water_profile.panel import WaterProfilePanel
    from app_渠系计算前端.panel_registry import PanelDescriptor, PanelRegistry
    from app_渠系计算前端.project_manager import ProjectManager
    app = QApplication.instance()
    registry = PanelRegistry([PanelDescriptor('water_profile', '水面线', 0, 'water_profile_panel', WaterProfilePanel, 'water_profile_panel')])
    manager = ProjectManager()
    manager.bind_runtime(registry)
    merged = registry.get('water_profile')
    backend = merged._batch_backend
    populate(backend, 1)
    if action in ('undo', 'redo'):
        paste(backend, '历史操作', col=module.COL_BUILDING_NAME)
        if action == 'redo':
            backend._undo_table()
    manager._clear_dirty()
    merged._section_sync_ready = True
    merged._transition_topology_prepared = True
    changes = []
    merged.data_changed.connect(lambda: changes.append(1))
    try:
        if action == 'paste':
            paste(backend, '新的输入', col=module.COL_BUILDING_NAME)
        elif action == 'undo':
            backend._undo_table()
        elif action == 'redo':
            backend._redo_table()
        elif action == 'apply_flow':
            backend.flow_segments_edit.setText('7.123456789')
            backend._apply_flow_segments()
        elif action == 'parameters':
            backend._push_undo_snapshot()
            backend._update_table_row(0, {'Q': '9.1', 'n': '0.014', 'slope_inv': '3000'}, '明渠-梯形')
        elif action == 'add':
            backend._add_row()
        elif action == 'insert':
            backend._insert_row_at(0)
        elif action == 'copy':
            backend.input_table.selectRow(0)
            backend._copy_row()
        elif action == 'clear':
            backend._clear_input(force=True, clear_shared=False)
        else:
            backend.input_table.selectRow(0)
            backend._del_row()
        assert manager.is_dirty
        assert not merged._section_sync_ready
        assert not merged._transition_topology_prepared
        assert changes == [1]
    finally:
        merged.deleteLater()
        manager.deleteLater()
        registry.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


def test_cancelled_input_action_keeps_existing_results_valid(panel, monkeypatch):
    from app_渠系计算前端.water_profile.panel import WaterProfilePanel
    merged = WaterProfilePanel()
    populate(merged._batch_backend, 1)
    merged._batch_backend.input_table.selectRow(0)
    merged._section_sync_ready = True
    changes = []
    merged.data_changed.connect(lambda: changes.append(1))
    monkeypatch.setattr(module, 'fluent_question', lambda *a, **k: False)
    try:
        merged._on_section_input_action(merged._batch_backend._del_row)
        assert merged._section_sync_ready
        assert changes == []
        assert merged._batch_backend.input_table.rowCount() == 1
    finally:
        merged.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QApplication.processEvents()


def test_detected_flow_and_undo_update_visible_settings_before_next_calculation(panel):
    from app_渠系计算前端.water_profile.panel import WaterProfilePanel
    merged = WaterProfilePanel()
    backend = merged._batch_backend
    populate(backend, 1)
    backend.flow_segments_edit.setText('5.0')
    try:
        paste(backend, '7.123456789012345', col=module.COL_Q)
        assert merged._section_flow_segments_edit.text() == '7.123456789012345'
        merged._copy_global_settings_to_batch_backend()
        assert backend.flow_segments_edit.text() == '7.123456789012345'
        backend._undo_table()
        assert merged._section_flow_segments_edit.text() == '5.0'
        backend._redo_table()
        assert merged._section_flow_segments_edit.text() == '7.123456789012345'
    finally:
        merged.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QApplication.processEvents()


def test_unrelated_edit_keeps_unapplied_visible_flow_input(panel):
    from app_渠系计算前端.water_profile.panel import WaterProfilePanel
    merged = WaterProfilePanel()
    backend = merged._batch_backend
    populate(backend, 1)
    backend.flow_segments_edit.setText('5.0')
    merged._section_flow_segments_edit.setText('9.87654321')
    try:
        backend.input_table.item(0, module.COL_BUILDING_NAME).setText('只修改名称')
        assert merged._section_flow_segments_edit.text() == '9.87654321'
        assert backend.flow_segments_edit.text() == '5.0'
    finally:
        merged.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QApplication.processEvents()


def test_case_navigator_pending_refresh_is_cancelled_with_widget(panel, monkeypatch):
    from app_渠系计算前端.case_manager import CaseTagNavigator
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda *args: errors.append(args))
    nav = CaseTagNavigator()
    nav._schedule_sync()
    nav.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()
    assert errors == []
