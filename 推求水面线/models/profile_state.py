"""水面线独立状态与表格快照，不依赖 Qt 或任何界面控件。"""

from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass, field
from typing import Any


PROFILE_ROW_ID_KEY = "_profile_row_id"
USER_DATA_ROLE = 256


def normalize_row_payload(value: Any) -> dict:
    """为稳定行身份准备字典，同时迁移旧补段标记并保留其他旧角色值。"""
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if value is None:
        return {}
    payload = {"_profile_legacy_user_role": copy.deepcopy(value)}
    if isinstance(value, str) and value == "auto_channel":
        payload["_auto_channel"] = True
    return payload


@dataclass
class ProfileRow:
    """一行的稳定身份、显示原文、精确值和人工采用参数。"""

    row_id: str
    cells: list[str] = field(default_factory=list)
    cell_data: dict[int, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)

    def numeric_value(self, column: int, default: float = 0.0) -> float:
        text = self.cells[column] if 0 <= column < len(self.cells) else ""
        payload = self.cell_data.get(0, {})
        numeric = payload.get("_numeric_display_values", {}) if isinstance(payload, dict) else {}
        exact = numeric.get(str(column)) if isinstance(numeric, dict) else None
        if isinstance(exact, dict) and exact.get("text") == text:
            value = exact.get("value")
            if isinstance(value, (int, float)) and math.isfinite(value):
                return value
        try:
            number = float(text)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError):
            return default

    def to_dict(self) -> dict:
        return {"row_id": self.row_id, "cells": list(self.cells),
                "cell_data": {str(k): copy.deepcopy(v) for k, v in self.cell_data.items()},
                "parameters": copy.deepcopy(self.parameters)}


@dataclass
class ProfileTableState:
    """可脱离界面计算和保存的完整表格快照。"""

    rows: list[ProfileRow] = field(default_factory=list)
    column_count: int = 44

    def parameter_values(self, name: str) -> dict[int, Any]:
        return {index: copy.deepcopy(row.parameters[name]) for index, row in enumerate(self.rows)
                if name in row.parameters}

    def to_dict(self) -> dict:
        return {"version": 1, "column_count": self.column_count,
                "rows": [row.to_dict() for row in self.rows]}

    @classmethod
    def from_dict(cls, value: dict) -> "ProfileTableState":
        if not isinstance(value, dict) or value.get("version", 1) != 1:
            raise ValueError("不支持的水面线表格状态版本")
        width = value.get("column_count", 44)
        if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
            raise ValueError("水面线表格列数必须是正整数")
        raw_rows = value.get("rows", [])
        if not isinstance(raw_rows, list):
            raise ValueError("水面线表格行必须是列表")
        rows = []
        seen = set()
        for raw in raw_rows:
            if not isinstance(raw, dict) or not isinstance(raw.get("cells", []), list):
                raise ValueError("水面线表格行数据不完整")
            if len(raw.get("cells", [])) > width:
                raise ValueError("水面线表格行宽超出声明列数")
            identity = str(raw.get("row_id", "") or "")
            if not identity or identity in seen:
                identity = uuid.uuid4().hex
            seen.add(identity)
            cell_data = raw.get("cell_data", {})
            parameters = raw.get("parameters", {})
            if not isinstance(cell_data, dict) or not isinstance(parameters, dict):
                raise ValueError("水面线表格附加参数必须是对象")
            normalized_data = {}
            for key, data in cell_data.items():
                if isinstance(key, bool) or not isinstance(key, (str, int)):
                    raise ValueError("水面线表格附加参数列号必须是整数")
                try:
                    column = int(key)
                except (TypeError, ValueError) as exc:
                    raise ValueError("水面线表格附加参数列号必须是整数") from exc
                if str(column) != str(key) or not 0 <= column < width:
                    raise ValueError("水面线表格附加参数列号超出范围")
                normalized_data[column] = copy.deepcopy(data)
            cells = [str(v) if v is not None else "" for v in raw.get("cells", [])]
            cells.extend([""] * (width - len(cells)))
            row = ProfileRow(identity, cells, normalized_data, copy.deepcopy(parameters))
            payload = normalize_row_payload(row.cell_data.get(0))
            payload[PROFILE_ROW_ID_KEY] = identity
            row.cell_data[0] = payload
            rows.append(row)
        return cls(rows, width)


class SnapshotCell:
    """供旧节点解码规则读取的纯数据单元格接口。"""

    def __init__(self, text: str, payload: Any):
        self._text = text
        self._payload = payload

    def text(self) -> str:
        return self._text

    def data(self, role: int) -> Any:
        return self._payload if role == USER_DATA_ROLE else None


class SnapshotTable:
    """只读适配器，兼容历史节点解码规则但不持有 QWidget。"""

    def __init__(self, state: ProfileTableState):
        self.state = state

    def rowCount(self) -> int:
        return len(self.state.rows)

    def columnCount(self) -> int:
        return self.state.column_count

    def item(self, row: int, column: int) -> SnapshotCell | None:
        if not (0 <= row < len(self.state.rows)):
            return None
        record = self.state.rows[row]
        if not 0 <= column < len(record.cells):
            return None
        return SnapshotCell(record.cells[column], record.cell_data.get(column))


@dataclass
class WaterProfileState:
    """当前水面线会话；输入、计算结果、表格快照与编辑参数集中持有。"""

    nodes: list[Any] = field(default_factory=list)
    calculated_nodes: list[Any] = field(default_factory=list)
    settings: Any = None
    table: ProfileTableState = field(default_factory=ProfileTableState)
    row_parameters: dict[str, dict[int, Any]] = field(default_factory=dict)
    revision: int = 0

    def touch(self) -> int:
        self.revision += 1
        return self.revision

    def replace_table(self, table: ProfileTableState) -> None:
        self.table = table

    def copy_for_calculation(self) -> "WaterProfileState":
        return copy.deepcopy(self)
