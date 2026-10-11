"""真实 Qt 表格的列宽缓存、批量删除以及撤销语义回归。"""

import copy
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('CODEX_FORCE_QTEXTBROWSER', '1')

import pytest
from PySide6.QtCore import Qt, QSignalBlocker, QEventLoop, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QTableWidgetSelectionRange

from app_渠系计算前端 import styles


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def table(app):
    widget = QTableWidget(4, 3)
    widget.resize(900, 300)
    widget.setHorizontalHeaderLabels(['名称', '流量', '说明'])
    for r in range(4):
        for c in range(3):
            widget.setItem(r, c, QTableWidgetItem(f'{r}.{c}'))
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_resize_reuses_natural_widths_and_can_shrink(table, monkeypatch, app):
    calls = []
    original = table.resizeColumnsToContents
    monkeypatch.setattr(table, 'resizeColumnsToContents', lambda: (calls.append(1), original()))
    styles.auto_resize_table(table)
    first = tuple(table.columnWidth(c) for c in range(3))
    for width in (700, 500, 800, 400):
        table.resize(width, 300)
        app.processEvents()
        styles.auto_resize_table(table, measure_contents=False)
    assert len(calls) == 1
    assert sum(table.columnWidth(c) for c in range(3)) < sum(first)
    assert all(table.columnWidth(c) >= table._column_content_widths[1][c] for c in range(3))


@pytest.mark.parametrize('change', ['text', 'header', 'row', 'font', 'hidden'])
def test_content_changes_invalidate_cached_widths(table, monkeypatch, change):
    styles.auto_resize_table(table)
    calls = []
    original = table.resizeColumnsToContents
    monkeypatch.setattr(table, 'resizeColumnsToContents', lambda: (calls.append(1), original()))
    # 即使填表代码屏蔽了表格信号，模型变化仍应使列宽缓存失效。
    with QSignalBlocker(table):
        if change == 'text':
            table.item(1, 1).setText('很长的数据内容' * 15)
        elif change == 'header':
            table.horizontalHeaderItem(2).setText('很长的表头说明' * 15)
        elif change == 'row':
            table.insertRow(4)
            table.setItem(4, 0, QTableWidgetItem('新增行'))
        elif change == 'font':
            table.setFont(QFont('Microsoft YaHei', 18))
        else:
            table.setColumnHidden(1, True)
    styles.auto_resize_table(table, measure_contents=False)
    assert len(calls) == 1
    if change in ('text', 'header'):
        column = 1 if change == 'text' else 2
        item = table.item(1, 1) if change == 'text' else table.horizontalHeaderItem(2)
        assert table.columnWidth(column) >= table.fontMetrics().horizontalAdvance(item.text()) + 26


def test_resize_requests_merge_into_one_owned_timer(table, monkeypatch):
    calls = []
    monkeypatch.setattr(styles, 'auto_resize_table', lambda *args, **kwargs: calls.append(kwargs))
    for _ in range(30):
        styles.schedule_table_resize(table)
    assert calls == []
    # 等实际信号，不用固定睡眠把系统忙时的调度延迟误报成业务失败。
    loop = QEventLoop()
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    table._column_resize_timer.timeout.connect(loop.quit)
    guard.start(2000)
    loop.exec()
    guard.stop()
    assert calls == [{'measure_contents': False}]
    assert table._column_resize_timer.parent() is table


@pytest.fixture
def panel(app, monkeypatch):
    from app_渠系计算前端.water_profile import panel as module
    from 推求水面线.models.data_models import ChannelNode
    from 推求水面线.models.enums import StructureType
    monkeypatch.setattr(module.InfoBar, 'success', lambda *a, **k: None)
    widget = module.WaterProfilePanel()
    widget.start_wl_edit.setText('100')
    nodes = []
    cumulative = 0.0
    for r in range(8):
        node = ChannelNode()
        node.name = f'节点{r}'
        node.flow_section = '1'
        node.structure_type = StructureType.from_string('明渠-梯形')
        node.flow = 1.25
        node.water_depth = 1.2
        node.section_params = {'B': 2.0, 'm': 1.0, 'h': 1.2}
        node.head_loss_reserve = 0.123456789 if r else 0.0
        node.head_loss_gate = 0.234567891 if r else 0.0
        node.head_loss_total = node.head_loss_reserve + node.head_loss_gate
        cumulative += node.head_loss_total
        node.head_loss_cumulative = cumulative
        node.water_level = 100.0 - cumulative
        node.bottom_elevation = node.water_level - node.water_depth
        node.top_elevation = node.bottom_elevation + 2.0
        nodes.append(node)
    widget.nodes = copy.deepcopy(nodes)
    widget.calculated_nodes = nodes
    widget._node_structure_heights = {r: 2.0 for r in range(8)}
    widget._update_table_from_nodes_full(nodes)
    widget._loss_undo_stack.clear()
    widget._loss_redo_stack.clear()
    widget._node_table_undo_stack.clear()
    widget._node_table_redo_stack.clear()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_selection_does_not_copy_table_but_edit_can_be_undone(panel, monkeypatch):
    calls = []
    original = panel._snapshot_editable_cols
    monkeypatch.setattr(panel, '_snapshot_editable_cols', lambda: (calls.append(1), original())[1])
    for r in range(1, 8):
        panel.node_table.setCurrentCell(r, 36)
    assert calls == []
    before = original()
    panel.node_table.item(7, 36).setText('0.8')
    assert len(calls) == 1
    assert panel.calculated_nodes[7].head_loss_reserve == pytest.approx(0.8)
    panel._undo_loss_edit()
    assert original() == before


def test_batch_delete_updates_all_totals_once_and_undo_restores_precision(panel, monkeypatch):
    before = panel._snapshot_editable_cols()
    before_values = [(n.head_loss_reserve, n.head_loss_gate, n.water_level) for n in panel.calculated_nodes]
    refreshed = []
    traversals = []
    dirty = []
    original = panel._recalc_downstream

    def recalc(row, **kwargs):
        if panel._loss_delete_batch is None:
            traversals.append((row, kwargs))
        return original(row, **kwargs)

    monkeypatch.setattr(panel, '_recalc_downstream', recalc)
    monkeypatch.setattr(panel, '_refresh_pressure_pipe_controls', lambda: refreshed.append(1))
    panel.data_changed.connect(lambda: dirty.append(1))
    panel.node_table.setRangeSelected(QTableWidgetSelectionRange(2, 36, 5, 37), True)
    panel.node_table._delete_selected_cells()
    after = panel._snapshot_editable_cols()
    assert len(traversals) == len(refreshed) == len(dirty) == 1
    assert traversals[0][0] == 2
    assert len(panel._loss_undo_stack) == 1
    for r in range(2, 6):
        assert panel._read_table_numeric_value(r, 39) == 0.0
        assert panel.calculated_nodes[r].head_loss_gate == 0.0
        assert panel._is_gate_loss_user_set_for_row(r, panel.calculated_nodes[r])
    assert panel.calculated_nodes[7].water_level == pytest.approx(100.0 - sum(
        n.head_loss_total for n in panel.calculated_nodes
    ))
    panel._undo_loss_edit()
    assert panel._snapshot_editable_cols() == before
    assert [(n.head_loss_reserve, n.head_loss_gate, n.water_level) for n in panel.calculated_nodes] == before_values
    panel._redo_loss_edit()
    assert panel._snapshot_editable_cols() == after


def test_undo_after_save_marks_dirty_and_reediting_same_cell_remains_reversible(panel):
    """撤销保存过的修改也应提示待保存；原地再编辑仍使用恢复后的旧值。"""
    panel.node_table.setCurrentCell(3, 36)
    original = panel.node_table.item(3, 36).text()
    panel.node_table.item(3, 36).setText('0.8')
    modified = []
    panel.data_changed.connect(lambda: modified.append(1))
    panel._undo_loss_edit()
    assert modified == [1]
    assert panel.node_table.item(3, 36).text() == original
    panel.node_table.item(3, 36).setText('0.9')
    panel._undo_loss_edit()
    assert panel.node_table.item(3, 36).text() == original


def test_frozen_table_delete_preserves_readonly_cells_and_notification_order(table):
    from app_渠系计算前端.frozen_table import FrozenColumnTableWidget
    widget = FrozenColumnTableWidget()
    widget.setRowCount(1)
    widget.setColumnCount(2)
    widget.setItem(0, 0, QTableWidgetItem('可以删除'))
    protected = QTableWidgetItem('只读')
    protected.setFlags(protected.flags() & ~Qt.ItemIsEditable)
    widget.setItem(0, 1, protected)
    widget.selectAll()
    events = []
    widget.deleteRequested.connect(lambda: events.append('start'))
    widget.cellChanged.connect(lambda r, c: events.append((r, c)))
    widget.deleteFinished.connect(lambda: events.append('finish'))
    widget._delete_selected_cells()
    assert events == ['start', (0, 0), 'finish']
    assert protected.text() == '只读'
    widget.deleteLater()


def test_batch_delete_keeps_pressure_override_semantics_and_one_summary(panel, monkeypatch):
    """混选过闸与有压水损，逐行覆盖值不能因统一递推而丢失。"""
    panel._apply_pressure_pipe_loss_override(2, manual_loss=0.456789123)
    panel._apply_pressure_pipe_loss_override(5, manual_loss=0.567891234)
    before = panel._snapshot_editable_cols()
    panel._loss_undo_stack.clear()
    summaries = []
    original = panel._rebuild_calculation_summary_state

    def rebuild(nodes):
        if panel._loss_delete_batch is None:
            summaries.append(1)
        return original(nodes)

    monkeypatch.setattr(panel, '_rebuild_calculation_summary_state', rebuild)
    panel.node_table.clearSelection()
    for row, col in ((2, 38), (3, 37), (5, 38)):
        panel.node_table.item(row, col).setSelected(True)
    panel.node_table._delete_selected_cells()
    after = panel._snapshot_editable_cols()
    assert summaries == [1]
    assert len(panel._loss_undo_stack) == 1
    assert panel.calculated_nodes[2].pressure_pipe_loss_override_m == 0.0
    assert panel.calculated_nodes[5].pressure_pipe_loss_override_m == 0.0
    assert panel.calculated_nodes[3].head_loss_gate == 0.0
    panel._undo_loss_edit()
    assert panel._snapshot_editable_cols() == before
    assert panel.calculated_nodes[2].pressure_pipe_loss_override_m == pytest.approx(0.456789123)
    panel._redo_loss_edit()
    assert panel._snapshot_editable_cols() == after
