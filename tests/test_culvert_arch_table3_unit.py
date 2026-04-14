# -*- coding: utf-8 -*-
"""圆拱直墙型暗涵在表3与补段对话框中的限制回归测试。"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.water_profile.panel import (
    ARCH_CULVERT_FAMILY_TEXT,
    CULVERT_FAMILY_TYPE_KEY,
    WaterProfilePanel,
)
from app_渠系计算前端.water_profile.water_profile_dialogs import (
    BatchChannelConfirmDialog,
    BuildingLengthDialog,
    OpenChannelDialog,
)


def _get_qapp():
    return QApplication.instance() or QApplication([])


class _FakeItem:
    """模拟表格单元格。"""

    def __init__(self, text="", payload=None):
        self._text = str(text)
        self._payload = payload

    def text(self):
        return self._text

    def data(self, role):
        if role == Qt.UserRole:
            return self._payload
        return None


class _FakeTable:
    """模拟表3节点表。"""

    def __init__(self, first_payload):
        self._items = {
            (0, 0): _FakeItem("1", first_payload),
            (0, 2): _FakeItem(ARCH_CULVERT_FAMILY_TEXT),
        }

    def rowCount(self):
        return 1

    def item(self, row, col):
        return self._items.get((row, col))


class _FakePanel:
    """承载表3来源判断逻辑的轻量对象。"""

    _is_arch_culvert_source_payload = staticmethod(WaterProfilePanel._is_arch_culvert_source_payload)
    _is_arch_culvert_source_row = WaterProfilePanel._is_arch_culvert_source_row
    _is_forbidden_manual_arch_culvert_row = WaterProfilePanel._is_forbidden_manual_arch_culvert_row
    _structure_selector_excluded_items_for_row = WaterProfilePanel._structure_selector_excluded_items_for_row

    def __init__(self, payload):
        self.node_table = _FakeTable(payload)


def _combo_items(combo):
    return [combo.itemText(index) for index in range(combo.count())]


def test_table3_rejects_hand_created_arch_culvert_row():
    panel = _FakePanel({})

    assert panel._is_arch_culvert_source_row(0) is False
    assert panel._is_forbidden_manual_arch_culvert_row(0, ARCH_CULVERT_FAMILY_TEXT) is True


def test_table3_accepts_arch_culvert_from_existing_source_payload():
    payload = {
        "_from_table1_source": True,
        CULVERT_FAMILY_TYPE_KEY: ARCH_CULVERT_FAMILY_TEXT,
    }
    panel = _FakePanel(payload)

    assert panel._is_arch_culvert_source_row(0) is True
    assert panel._is_forbidden_manual_arch_culvert_row(0, ARCH_CULVERT_FAMILY_TEXT) is False


def test_table3_structure_selector_hides_arch_culvert_for_manual_row():
    panel = _FakePanel({})

    assert ARCH_CULVERT_FAMILY_TEXT in panel._structure_selector_excluded_items_for_row(0)


def test_table3_structure_selector_keeps_arch_culvert_for_source_row():
    payload = {
        "_from_table1_source": True,
        CULVERT_FAMILY_TYPE_KEY: ARCH_CULVERT_FAMILY_TEXT,
    }
    panel = _FakePanel(payload)

    assert ARCH_CULVERT_FAMILY_TEXT not in panel._structure_selector_excluded_items_for_row(0)


def test_batch_dialog_keeps_arch_culvert_only_for_source_carried_row():
    _get_qapp()
    gaps = [
        {
            "prev_name": "上游圆拱暗涵",
            "prev_struct": ARCH_CULVERT_FAMILY_TEXT,
            "next_name": "下游",
            "next_struct": "倒虹吸",
            "available_length": 18.0,
            "flow": 2.88,
            "flow_section": "1",
            "reference_segment": {
                "structure_type": ARCH_CULVERT_FAMILY_TEXT,
                "flow_section": "1",
                "bottom_width": 2.6,
                "structure_height": 3.0,
                "theta_deg": 140.0,
                "water_depth": 1.5,
                "roughness": 0.014,
                "slope_inv": 3000,
                "side_slope": 0.0,
            },
            "upstream_channel": None,
            "has_reference": True,
            "has_upstream": True,
        },
        {
            "prev_name": "上游明渠",
            "prev_struct": "明渠-梯形",
            "next_name": "下游明渠",
            "next_struct": "倒虹吸",
            "available_length": 15.0,
            "flow": 2.88,
            "flow_section": "1",
            "reference_segment": None,
            "upstream_channel": None,
            "has_reference": False,
            "has_upstream": False,
        },
    ]

    dialog = BatchChannelConfirmDialog(None, len(gaps), gaps)
    first_combo = dialog._row_widgets[0]["type_combo"]
    second_combo = dialog._row_widgets[1]["type_combo"]

    assert first_combo.currentText() == ARCH_CULVERT_FAMILY_TEXT
    assert ARCH_CULVERT_FAMILY_TEXT in _combo_items(first_combo)
    assert ARCH_CULVERT_FAMILY_TEXT not in _combo_items(second_combo)


def test_open_channel_dialog_hides_arch_culvert_from_manual_choices():
    app = _get_qapp()
    dialog = OpenChannelDialog(
        None,
        upstream_channel={
            "structure_type": ARCH_CULVERT_FAMILY_TEXT,
            "bottom_width": 2.6,
            "structure_height": 3.0,
            "theta_deg": 140.0,
            "water_depth": 1.5,
            "roughness": 0.014,
            "slope_inv": 3000,
            "side_slope": 0.0,
            "flow_section": "1",
            "flow": 2.88,
        },
        available_length=20.0,
        prev_structure=ARCH_CULVERT_FAMILY_TEXT,
        next_structure="倒虹吸",
        flow_section="1",
        flow=2.88,
    )
    dialog.show()
    app.processEvents()

    assert dialog.type_combo.currentText() == ARCH_CULVERT_FAMILY_TEXT
    assert ARCH_CULVERT_FAMILY_TEXT in _combo_items(dialog.type_combo)

    dialog.rb_manual.setChecked(True)
    dialog._on_source_change()
    app.processEvents()

    assert ARCH_CULVERT_FAMILY_TEXT not in _combo_items(dialog.type_combo)


def test_building_length_dialog_recognizes_culvert_family_as_building():
    assert BuildingLengthDialog._is_building_type("暗涵-矩形") is True
    assert BuildingLengthDialog._is_building_type("暗涵-圆拱直墙型") is True
