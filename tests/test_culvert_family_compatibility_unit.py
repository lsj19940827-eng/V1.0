# -*- coding: utf-8 -*-
"""暗涵家族兼容、旁支映射与项目读写的回归测试。"""

import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app_渠系计算前端.batch.panel as batch_panel_mod
import app_渠系计算前端.siphon.dialogs as siphon_dialogs

summary_mod = importlib.import_module("calc_渠系计算算法内核.生成断面汇总表")


class _TextField:
    """模拟只读写文本的输入控件。"""

    def __init__(self, value=""):
        self.value = value

    def text(self):
        return self.value

    def setText(self, value):
        self.value = value


class _ComboField:
    """模拟下拉框的最小行为。"""

    def __init__(self, options=None, current=""):
        self.options = list(options or [])
        self.current = current

    def currentText(self):
        return self.current

    def findText(self, text):
        try:
            return self.options.index(text)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self.current = self.options[index]


class _CheckField:
    """模拟复选框的最小行为。"""

    def __init__(self, checked=False):
        self.checked = checked

    def isChecked(self):
        return self.checked

    def setChecked(self, checked):
        self.checked = bool(checked)


class _DetailText:
    """模拟结果文本框。"""

    def __init__(self):
        self.cleared = False

    def clear(self):
        self.cleared = True


class _TableItem:
    """模拟表格单元格。"""

    def __init__(self, value=""):
        self._value = value
        self._alignment = None

    def text(self):
        return self._value

    def setTextAlignment(self, alignment):
        self._alignment = alignment


class _Table:
    """模拟批量页保存/加载所需的最小表格接口。"""

    def __init__(self, column_count):
        self._column_count = column_count
        self._rows = []

    def rowCount(self):
        return len(self._rows)

    def columnCount(self):
        return self._column_count

    def item(self, row, col):
        return self._rows[row][col]

    def setItem(self, row, col, item):
        self._rows[row][col] = item

    def setRowCount(self, count):
        current = len(self._rows)
        if count > current:
            for _ in range(count - current):
                self._rows.append([None] * self._column_count)
        else:
            self._rows = self._rows[:count]


def _make_batch_panel():
    """构造一个可供序列化测试的最小 BatchPanel 对象。"""
    panel = batch_panel_mod.BatchPanel.__new__(batch_panel_mod.BatchPanel)
    panel.input_table = _Table(len(batch_panel_mod.INPUT_HEADERS))
    panel.channel_name_edit = _TextField("测试渠道")
    panel.channel_level_combo = _ComboField(["总干渠", "支渠"], "支渠")
    panel.start_wl_edit = _TextField("10.50")
    panel.start_station_edit = _TextField("0+000.000")
    panel.flow_segments_edit = _TextField("1")
    panel.inc_cb = _CheckField(True)
    panel.detail_cb = _CheckField(True)
    panel.result_table = _Table(1)
    panel.detail_text = _DetailText()
    panel._set_excel_import_session_active = lambda *_args, **_kwargs: None
    panel.batch_results = []
    panel._detail_text_cache = ""
    panel._is_sample_data = False
    return panel


def _make_row(structure_type):
    """构造一行表1数据。"""
    row = [""] * len(batch_panel_mod.INPUT_HEADERS)
    row[0] = "1"
    row[1] = "第一流量段"
    row[2] = "建筑物"
    row[3] = structure_type
    return row


@pytest.mark.parametrize("legacy_type", ["暗渠", "矩形暗渠", "矩形暗涵"])
def test_batch_panel_project_save_normalizes_legacy_rect_culvert_labels(legacy_type):
    """表1保存项目时应把旧矩形暗涵名称统一成标准口径。"""
    panel = _make_batch_panel()
    panel.input_table.setRowCount(1)
    row = _make_row(legacy_type)
    for col_idx, value in enumerate(row):
        panel.input_table.setItem(0, col_idx, _TableItem(value))

    payload = batch_panel_mod.BatchPanel.to_project_dict(panel)

    assert payload["input_rows"][0][3] == "暗涵-矩形"


@pytest.mark.parametrize("legacy_type", ["暗渠", "矩形暗渠", "矩形暗涵"])
def test_batch_panel_project_load_normalizes_legacy_rect_culvert_labels(legacy_type):
    """表1加载旧项目时应回显为标准矩形暗涵名称。"""
    panel = _make_batch_panel()

    batch_panel_mod.BatchPanel.from_project_dict(
        panel,
        {"input_rows": [_make_row(legacy_type)]},
        skip_dirty_signal=True,
    )

    assert panel.input_table.item(0, 3).text() == "暗涵-矩形"


@pytest.mark.parametrize(
    ("raw_type", "expected_type", "expected_category"),
    [
        ("暗渠", "暗涵-矩形", "rectangular"),
        ("矩形暗渠", "暗涵-矩形", "rectangular"),
        ("矩形暗涵", "暗涵-矩形", "rectangular"),
        ("暗涵-矩形", "暗涵-矩形", "rectangular"),
        ("圆拱直墙型暗涵", "暗涵-圆拱直墙型", "arch_wall"),
        ("暗涵-圆拱直墙型", "暗涵-圆拱直墙型", "arch_wall"),
    ],
)
def test_outlet_shape_dialog_normalizes_culvert_family_aliases(raw_type, expected_type, expected_category):
    """倒虹吸出口局部阻力弹窗应把暗涵别名归到正确断面分类。"""
    normalized = siphon_dialogs.normalize_outlet_section_type(raw_type)

    assert normalized == expected_type
    assert siphon_dialogs.OutletShapeDialog._SECTION_CATEGORIES[normalized] == expected_category


@pytest.mark.parametrize(
    ("structure_type", "culvert_family_type", "expected"),
    [
        ("暗渠", "", "rect_culvert"),
        ("矩形暗渠", "", "rect_culvert"),
        ("矩形暗涵", "", "rect_culvert"),
        ("暗涵-矩形", "", "rect_culvert"),
        ("圆拱直墙型暗涵", "", "rect_culvert_arch"),
        ("矩形暗涵", "暗涵-圆拱直墙型", "rect_culvert_arch"),
    ],
)
def test_section_summary_classifies_legacy_culvert_aliases(structure_type, culvert_family_type, expected):
    """断面汇总分类应兼容旧暗涵别名和家族标记。"""

    class _Node:
        pass

    node = _Node()
    node.structure_type = structure_type
    node.section_params = {}
    if culvert_family_type:
        node.section_params["culvert_family_type"] = culvert_family_type
    node.is_inverted_siphon = False

    assert summary_mod._classify_structure(node) == expected
