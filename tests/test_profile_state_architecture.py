# -*- coding: utf-8 -*-
"""独立状态、精确数值和稳定行身份的行为回归。"""

import copy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from 推求水面线.models.data_models import ChannelNode
from 推求水面线.models.profile_state import (
    PROFILE_ROW_ID_KEY, USER_DATA_ROLE, ProfileRow, ProfileTableState, SnapshotTable, WaterProfileState,
)
from 推求水面线.models.profile_node_codec import ProfileNodeCodec

ROOT = Path(__file__).resolve().parents[1]


def _row(identity="row-a"):
    """包含隐藏精度、旧 IP 元数据和独立行参数的合法表3输入。"""
    cells = [""] * 44
    for column, value in {0: "1", 1: "测试渠段", 2: "明渠-梯形", 4: "IP7", 5: "100.1234567",
                          6: "200.7654321", 7: "0", 13: "南支1+234.568", 20: "2", 23: "1.5",
                          24: "0.014", 25: "1000", 26: "0.812", 27: "0.6", 31: "1.235",
                          41: "100.123"}.items():
        cells[column] = value
    exact_values = {13: 1234.5678912, 26: 0.8123456789, 31: 1.2345678912, 41: 100.123456789}
    payload = {PROFILE_ROW_ID_KEY: identity, "_numeric_display_values": {
        str(column): {"text": cells[column], "value": value} for column, value in exact_values.items()
    }}
    return ProfileRow(identity, cells, {
        0: payload, 4: {"_raw_ip_number": 7, "_display_ip_number": 7}
    }, {"structure_heights": 1.8, "chamfer_params": {"chamfer_angle": 45.0, "chamfer_length": 0.1},
        "velocity_increased": 1.5})


def test_state_and_node_codec_load_without_qt_or_frontend():
    """独立进程拒绝 GUI 导入，仍能装载状态与节点解码服务。"""
    script = """
import sys, importlib.abc, platform
# 独立进程不会继承父进程的补丁，先应用正式启动器同等的 WMI 防护。
if sys.platform.startswith('win'):
    def _disabled_wmi_query(*args, **kwargs):
        raise OSError('Windows WMI query disabled to avoid startup hang')
    platform._wmi_query = _disabled_wmi_query
    if hasattr(platform, '_wmi'):
        platform._wmi = None
    platform._uname_cache = None
class BlockGui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PySide6', 'PyQt', 'qfluentwidgets', 'app_渠系计算前端')):
            raise AssertionError('纯状态或节点解码不应导入 GUI: ' + fullname)
sys.meta_path.insert(0, BlockGui())
from 推求水面线.models.profile_state import ProfileTableState
from 推求水面线.models.profile_node_codec import ProfileNodeCodec
assert ProfileNodeCodec(ProfileTableState()).decode() == []
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_json_roundtrip_preserves_identity_precision_parameters_and_ip_metadata():
    """真实 JSON 往返后显示原文、计算精度、行参数及特殊列元数据都不能丢失。"""
    original = ProfileTableState([_row()])
    payload = json.loads(json.dumps(original.to_dict(), ensure_ascii=False))
    restored = ProfileTableState.from_dict(payload)
    assert restored.to_dict() == original.to_dict()
    node = ProfileNodeCodec(restored, design_flows_text="0.8", roughness_text="0.014").decode()[0]
    assert node.profile_row_id == "row-a"
    assert node.flow == 0.8123456789
    assert node.velocity == 1.2345678912
    assert node.water_level == 100.123456789
    assert node.station_ip == 1234.5678912
    assert node.x == 100.1234567
    assert node.y == 200.7654321
    assert node.ip_number == node.display_ip_number == 7
    assert node.structure_height == 1.8
    assert node.velocity_increased == 1.5
    assert node.section_params["chamfer_length"] == 0.1


def test_text_edit_invalidates_only_that_cells_cached_exact_value():
    """未编辑列沿用精确数值，编辑列立即采用新文本，不能套旧缓存。"""
    row = _row()
    row.cells[31] = "2.50"
    row.cells[13] = "南支2+345.678"
    state = ProfileTableState([row])
    assert row.numeric_value(31) == 2.5
    assert row.numeric_value(26) == 0.8123456789
    node = ProfileNodeCodec(state).decode()[0]
    assert node.velocity == 2.5
    assert node.station_ip == 2345.678
    assert node.flow == 0.8123456789


@pytest.mark.parametrize("bad", [None, [], "invalid", 10])
def test_invalid_legacy_precision_payload_uses_current_text(bad):
    """旧工程损坏的精度缓存不应阻止读取合法表格文本。"""
    row = _row()
    row.cell_data[0]["_numeric_display_values"] = bad
    assert row.numeric_value(31) == 1.235
    node = ProfileNodeCodec(ProfileTableState([row])).decode()[0]
    assert node.velocity == 1.235
    assert node.station_ip == 1234.568


@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "", "非数值"])
def test_numeric_reader_never_returns_nonfinite_or_invalid_text(text):
    row = ProfileRow("r", [text])
    assert row.numeric_value(0, default=9.0) == 9.0


def test_missing_and_duplicate_ids_migrate_once_and_remain_stable():
    """旧工程缺少身份或复制带来重复身份时补新值，保存后不再漂移。"""
    payload = {"rows": [
        {"row_id": "stable", "cells": ["1"]},
        {"row_id": "stable", "cells": ["2"]},
        {"cells": ["3"]},
    ]}
    state = ProfileTableState.from_dict(payload)
    identities = [row.row_id for row in state.rows]
    assert identities[0] == "stable"
    assert len(set(identities)) == 3 and all(identities)
    assert all(len(row.cells) == 44 for row in state.rows)
    assert all(row.cell_data[0][PROFILE_ROW_ID_KEY] == row.row_id for row in state.rows)
    assert [row.row_id for row in ProfileTableState.from_dict(state.to_dict()).rows] == identities


@pytest.mark.parametrize("column_count", [-1, 0, 2.5, True, "44", None])
def test_invalid_declared_column_count_is_rejected(column_count):
    with pytest.raises(ValueError):
        ProfileTableState.from_dict({"column_count": column_count, "rows": []})


@pytest.mark.parametrize("key", [-1, "-1", 44, "44", "x", "1.5", 1.5, True])
def test_invalid_hidden_metadata_column_is_rejected(key):
    with pytest.raises(ValueError):
        ProfileTableState.from_dict({"rows": [{"cells": ["1"], "cell_data": {key: {}}}]})


@pytest.mark.parametrize("payload", [
    {"version": 2}, {"rows": {}}, {"rows": [None]},
    {"rows": [{"cells": {}}]}, {"rows": [{"cells": [""] * 45}]},
    {"rows": [{"cells": [], "cell_data": []}]},
    {"rows": [{"cells": [], "parameters": []}]},
])
def test_corrupt_table_state_is_rejected_before_restoration(payload):
    with pytest.raises(ValueError):
        ProfileTableState.from_dict(payload)


def test_background_copy_and_parameter_reads_are_detached():
    """后台计算副本和外部读取的参数都不能反写当前编辑状态。"""
    state = WaterProfileState(nodes=[ChannelNode(profile_row_id="row-a", section_params={"B": 2.0})],
                              table=ProfileTableState([_row()]), row_parameters={"chamfer_params": {0: {"length": 0.1}}})
    copied = state.copy_for_calculation()
    copied.nodes[0].section_params["B"] = 99
    copied.table.rows[0].cells[1] = "changed"
    copied.row_parameters["chamfer_params"][0]["length"] = 9
    parameters = state.table.parameter_values("chamfer_params")
    parameters[0]["chamfer_length"] = 100
    assert state.nodes[0].section_params["B"] == 2.0
    assert state.table.rows[0].cells[1] == "测试渠段"
    assert state.row_parameters["chamfer_params"][0]["length"] == 0.1
    assert state.table.rows[0].parameters["chamfer_params"]["chamfer_length"] == 0.1
    assert copied.touch() == 1 and state.revision == 0


class _Cell:
    """只暴露适配器实际使用的单元格接口，不替换全局 Qt 模块。"""

    def __init__(self, text="", payload=None):
        self.value = text
        self.payload = copy.deepcopy(payload)

    def text(self):
        return self.value

    def data(self, role):
        return self.payload if role == USER_DATA_ROLE else None

    def setData(self, role, payload):
        assert role == USER_DATA_ROLE
        self.payload = copy.deepcopy(payload)


class _Table:
    """用于独立验证元数据适配的局部表格对象。"""

    def __init__(self, rows):
        self.items = [[_Cell(text, row.cell_data.get(column)) for column, text in enumerate(row.cells)]
                      for row in rows]
        self.blocked = False

    def rowCount(self):
        return len(self.items)

    def columnCount(self):
        return 44

    def item(self, row, column):
        return self.items[row][column]

    def setItem(self, row, column, item):
        self.items[row][column] = item

    def blockSignals(self, blocked):
        previous = self.blocked
        self.blocked = blocked
        return previous


def test_table_capture_preserves_ids_after_reorder_and_renews_only_duplicates():
    """调序不改变既有身份，复制行仅给副本分配新身份并保留原数值元数据。"""
    from app_渠系计算前端.water_profile.table_state_adapter import capture_table_state
    table = _Table([_row("a"), _row("b")])
    first = capture_table_state(table)
    table.items.reverse()
    second = capture_table_state(table)
    assert [row.row_id for row in first.rows] == ["a", "b"]
    assert [row.row_id for row in second.rows] == ["b", "a"]
    table.items.append(copy.deepcopy(table.items[0]))
    copied = capture_table_state(table)
    assert [row.row_id for row in copied.rows[:2]] == ["b", "a"]
    assert copied.rows[2].row_id not in {"a", "b"}
    assert copied.rows[2].numeric_value(31) == 1.2345678912
    assert not table.blocked


def test_metadata_restore_preserves_precision_and_previous_signal_state():
    from app_渠系计算前端.water_profile.table_state_adapter import apply_row_metadata, capture_table_state
    row = _row()
    table = _Table([ProfileRow("", list(row.cells))])
    table.blocked = True
    apply_row_metadata(table, ProfileTableState([row]))
    restored = capture_table_state(table)
    assert table.blocked is True
    assert restored.rows[0].row_id == "row-a"
    assert restored.rows[0].numeric_value(26) == 0.8123456789
    assert restored.rows[0].cell_data[4]["_raw_ip_number"] == 7


def test_capture_does_not_reassign_existing_calculation_ids_by_new_position():
    """表格调序后旧计算节点保持各自身份，不能按等长数组位置重新命名。"""
    from app_渠系计算前端.water_profile.panel import WaterProfilePanel
    nodes = [ChannelNode(profile_row_id="a"), ChannelNode(profile_row_id="b")]
    state = WaterProfileState(nodes=nodes, calculated_nodes=copy.deepcopy(nodes))
    holder = SimpleNamespace(
        _get_profile_state=lambda: state, node_table=_Table([_row("b"), _row("a")]),
        _node_structure_heights={}, _node_chamfer_params={}, _node_u_params={}, _node_velocity_increased={},
    )
    captured = WaterProfilePanel._capture_profile_table_state(holder)
    assert [row.row_id for row in captured.rows] == ["b", "a"]
    assert [node.profile_row_id for node in state.nodes] == ["a", "b"]
    assert [node.profile_row_id for node in state.calculated_nodes] == ["a", "b"]
