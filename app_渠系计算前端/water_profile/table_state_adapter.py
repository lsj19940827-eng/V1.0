"""Qt 表格与纯水面线状态之间的适配，只在界面线程调用。"""

import copy
import uuid

from PySide6.QtWidgets import QTableWidgetItem

from 推求水面线.models.profile_state import (
    PROFILE_ROW_ID_KEY, USER_DATA_ROLE, ProfileRow, ProfileTableState, normalize_row_payload,
)


def capture_table_state(table, parameter_fields=None) -> ProfileTableState:
    """一次读取控件；复用已有身份，复制行自动分配新身份。"""
    state = ProfileTableState(column_count=table.columnCount())
    fields = parameter_fields or {}
    seen = set()
    block_signals = getattr(table, 'blockSignals', None)
    previous = block_signals(True) if callable(block_signals) else False
    try:
        for index in range(table.rowCount()):
            cells = []
            cell_data = {}
            for column in range(table.columnCount()):
                item = table.item(index, column)
                cells.append(item.text() if item else "")
                if item is not None:
                    payload = item.data(USER_DATA_ROLE)
                    if payload is not None:
                        cell_data[column] = copy.deepcopy(payload)
            payload = normalize_row_payload(cell_data.get(0))
            identity = str(payload.get(PROFILE_ROW_ID_KEY, "") or "")
            if not identity or identity in seen:
                identity = uuid.uuid4().hex
                payload[PROFILE_ROW_ID_KEY] = identity
                first = table.item(index, 0)
                if first is None:
                    first = QTableWidgetItem(cells[0] if cells else "")
                    table.setItem(index, 0, first)
                first.setData(USER_DATA_ROLE, payload)
            seen.add(identity)
            cell_data[0] = payload
            parameters = {name: copy.deepcopy(values[index]) for name, values in fields.items() if index in values}
            state.rows.append(ProfileRow(identity, cells, cell_data, parameters))
    finally:
        if callable(block_signals):
            block_signals(previous)
    return state


def apply_row_metadata(table, state: ProfileTableState) -> None:
    """文字/样式仍由页面渲染，统一回填稳定身份和所有隐藏精度数据。"""
    previous = table.blockSignals(True)
    try:
        for index, row in enumerate(state.rows):
            if index >= table.rowCount():
                break
            # 完整快照中缺失的角色也必须清除，不能沿用旧节点渲染时生成的元数据。
            for column in range(table.columnCount()):
                payload = row.cell_data.get(column)
                item = table.item(index, column)
                if item is None:
                    if payload is None:
                        continue
                    item = QTableWidgetItem(row.cells[column] if column < len(row.cells) else "")
                    table.setItem(index, column, item)
                item.setData(USER_DATA_ROLE, copy.deepcopy(payload))
    finally:
        table.blockSignals(previous)
