# -*- coding: utf-8 -*-
"""平底圆形隧洞在表3限制与 xx管 摘要链路中的轻量回归测试。"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.water_profile.panel import (
    FLAT_BOTTOM_TUNNEL_SOURCE_ROLE_KEY,
    WaterProfilePanel,
)
import app_渠系计算前端.water_profile.cad_tools as cad_tools


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
            (0, 2): _FakeItem("隧洞-平底圆形"),
        }

    def rowCount(self):
        return 1

    def item(self, row, col):
        return self._items.get((row, col))


class _FakePanel:
    """承载表3来源判断逻辑的轻量对象。"""

    _is_flat_bottom_circle_source_payload = staticmethod(WaterProfilePanel._is_flat_bottom_circle_source_payload)
    _is_flat_bottom_circle_source_row = WaterProfilePanel._is_flat_bottom_circle_source_row
    _is_forbidden_manual_flat_bottom_circle_row = WaterProfilePanel._is_forbidden_manual_flat_bottom_circle_row

    def __init__(self, payload):
        self.node_table = _FakeTable(payload)


def test_table3_rejects_hand_created_flat_bottom_circle_row():
    """手工新建的平底圆形行应被立即判为不允许。"""
    panel = _FakePanel(
        {
            "_from_table1_source": False,
            FLAT_BOTTOM_TUNNEL_SOURCE_ROLE_KEY: False,
        }
    )

    assert panel._is_flat_bottom_circle_source_row(0) is False
    assert panel._is_forbidden_manual_flat_bottom_circle_row(0, "隧洞-平底圆形") is True


def test_table3_rejects_pasted_flat_bottom_circle_without_explicit_source_payload():
    """粘贴或批量改写出来的平底圆形，只要没有显式来源标记也应被拦下。"""
    panel = _FakePanel(None)

    assert panel._is_flat_bottom_circle_source_row(0) is False
    assert panel._is_forbidden_manual_flat_bottom_circle_row(0, "隧洞-平底圆形") is True


def test_table3_accepts_flat_bottom_circle_from_table1_or_shared_import():
    """表1同步和共享结果导入共用显式来源标记，应允许通过。"""
    payload = {
        "_from_table1_source": True,
        FLAT_BOTTOM_TUNNEL_SOURCE_ROLE_KEY: True,
    }
    panel = _FakePanel(payload)

    assert panel._is_flat_bottom_circle_source_row(0) is True
    assert panel._is_forbidden_manual_flat_bottom_circle_row(0, "隧洞-平底圆形") is False


def test_flat_bottom_circle_source_payload_defaults_to_forbidden_without_explicit_flag():
    """缺少显式来源标记时，不应把平底圆形误判为合法来源。"""
    assert WaterProfilePanel._is_flat_bottom_circle_source_payload(None) is False
    assert WaterProfilePanel._is_flat_bottom_circle_source_payload({}) is False
    assert WaterProfilePanel._is_flat_bottom_circle_source_payload({"_from_table1_source": False}) is False
    assert WaterProfilePanel._is_flat_bottom_circle_source_payload({"_from_table1_source": True}) is True


def test_xxpipe_profile_section_text_reads_flat_bottom_circle_diameter_from_merged_params():
    """xx管 摘要应从合并后的隧洞参数中读取平底圆形的 D 和 B。"""
    node = SimpleNamespace(section_params={})
    manager_row = {
        "tunnel_section_type": "隧洞-平底圆形",
        "tunnel_section_params": {"D": 4.0, "B": 2.0},
    }

    text = cad_tools._format_xxpipe_profile_section_text(node, "隧洞-平底圆形", manager_row=manager_row)

    assert text == "平底圆形隧洞 D=4m B=2m"
