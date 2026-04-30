# -*- coding: utf-8 -*-
"""圆拱直墙型隧洞直墙高度在单项页与批量页中的回归测试。"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.batch.panel import (
    BatchPanel,
    COL_ARCH_H_STRAIGHT,
    COL_COMPOUND_H1,
    COL_TURN_RADIUS,
    INPUT_HEADERS,
    SectionParameterDialog,
)
import app_渠系计算前端.batch.panel as batch_panel_mod
from app_渠系计算前端.tunnel.panel import TunnelPanel


class _FakeTable:
    """批量表格的最小替身。"""

    def __init__(self):
        self._items = {}

    def blockSignals(self, _blocked):
        return None

    def setItem(self, row, col, item):
        self._items[(row, col)] = item

    def item(self, row, col):
        return self._items.get((row, col))


class _FakeEntry:
    """模拟参数弹窗输入框。"""

    def __init__(self, text):
        self._text = str(text)

    def text(self):
        return self._text


def _build_arch_case(**overrides):
    """构造圆拱直墙型隧洞工况字典。"""
    case = {
        "section_type": "圆拱直墙型",
        "Q": "5.0",
        "n": "0.014",
        "slope_inv": "2000",
        "v_min": "0.1",
        "v_max": "100",
        "inc_checked": False,
        "inc_pct": "",
        "inc_q_text": "",
        "detail_checked": True,
        "theta_deg": "150",
        "B_hs": "3.0",
        "H_straight_hs": "1.2",
    }
    case.update(overrides)
    return case


def test_tunnel_parse_case_passes_manual_wall_height_to_kernel():
    """单项页计算入口应把 H直 传给内核。"""
    inp, res = TunnelPanel._parse_and_calc_case(None, _build_arch_case(), 1)

    assert inp["manual_B"] == pytest.approx(3.0)
    assert inp["manual_H_straight"] == pytest.approx(1.2)
    assert res["success"] is True
    assert res["used_manual_H_straight"] is True
    assert res["H_straight"] == pytest.approx(1.2)


def test_tunnel_parse_case_rejects_wall_height_without_bottom_width():
    """填写 H直 但未填写 B 时应给出明确错误。"""
    with pytest.raises(ValueError, match="底宽 B"):
        TunnelPanel._parse_and_calc_case(
            None,
            _build_arch_case(B_hs="", H_straight_hs="1.2"),
            1,
        )


def test_batch_input_headers_append_wall_height_column_without_moving_old_columns():
    """批量输入表应在末尾追加 H直 列，避免旧列错位。"""
    assert INPUT_HEADERS[COL_TURN_RADIUS] == "转弯半径(m)"
    assert INPUT_HEADERS[COL_COMPOUND_H1] == "平台高差h1(m)"
    assert INPUT_HEADERS[COL_ARCH_H_STRAIGHT] == "直墙高度H直(m)"
    assert COL_ARCH_H_STRAIGHT == len(INPUT_HEADERS) - 1


def test_batch_calculate_single_passes_manual_wall_height_to_kernel():
    """批量页分发计算时应支持固定 H直。"""
    panel = BatchPanel.__new__(BatchPanel)

    result = BatchPanel._calculate_single(
        panel,
        "隧洞-圆拱直墙型",
        5.0,
        0.014,
        2000,
        0.1,
        100.0,
        b=3.0,
        theta_deg=150.0,
        manual_H_straight=1.2,
        manual_increase_percent=0,
    )

    assert result["success"] is True
    assert result["used_manual_H_straight"] is True
    assert result["H_straight"] == pytest.approx(1.2)


def test_batch_panel_update_table_row_writes_back_arch_wall_height():
    """批量参数弹窗回填时应写回 H直 追加列。"""
    panel = BatchPanel.__new__(BatchPanel)
    panel.input_table = _FakeTable()
    panel._get_row_data = lambda _row: [""] * len(INPUT_HEADERS)
    panel._normalize_row = lambda values, length: list(values[:length]) + [""] * max(0, length - len(values))

    BatchPanel._update_table_row(
        panel,
        0,
        {
            "Q": 5.0,
            "n": 0.014,
            "slope_inv": 2000.0,
            "v_min": 0.1,
            "v_max": 100.0,
            "B": 3.0,
            "theta": 150.0,
            "H_straight": 1.2,
        },
        "隧洞-圆拱直墙型",
    )

    assert panel.input_table.item(0, 10).text() == "3.0"
    assert panel.input_table.item(0, 17).text() == "150.0"
    assert panel.input_table.item(0, COL_ARCH_H_STRAIGHT).text() == "1.2"


def test_section_parameter_dialog_accepts_arch_wall_height(monkeypatch):
    """批量参数弹窗应校验并返回 H直。"""
    dialog = SectionParameterDialog.__new__(SectionParameterDialog)
    dialog.section_type = "隧洞-圆拱直墙型"
    dialog.result = None
    dialog._entries = {
        "Q": _FakeEntry("5.0"),
        "n": _FakeEntry("0.014"),
        "slope_inv": _FakeEntry("2000"),
        "v_min": _FakeEntry("0.1"),
        "v_max": _FakeEntry("100"),
        "theta": _FakeEntry("150"),
        "B": _FakeEntry("3.0"),
        "H_straight": _FakeEntry("1.2"),
    }
    accepted = []
    dialog.accept = lambda: accepted.append(True)
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    SectionParameterDialog._on_confirm(dialog)

    assert accepted == [True]
    assert dialog.result["B"] == pytest.approx(3.0)
    assert dialog.result["theta"] == pytest.approx(150.0)
    assert dialog.result["H_straight"] == pytest.approx(1.2)


def test_section_parameter_dialog_rejects_arch_wall_height_without_bottom_width(monkeypatch):
    """批量弹窗中 H直 有值时 B 必填。"""
    dialog = SectionParameterDialog.__new__(SectionParameterDialog)
    dialog.section_type = "隧洞-圆拱直墙型"
    dialog.result = None
    dialog._entries = {
        "Q": _FakeEntry("5.0"),
        "n": _FakeEntry("0.014"),
        "slope_inv": _FakeEntry("2000"),
        "v_min": _FakeEntry("0.1"),
        "v_max": _FakeEntry("100"),
        "theta": _FakeEntry("150"),
        "B": _FakeEntry(""),
        "H_straight": _FakeEntry("1.2"),
    }
    errors = []
    dialog.accept = lambda: None
    monkeypatch.setattr(batch_panel_mod, "fluent_info", lambda _parent, _title, content: errors.append(content))
    monkeypatch.setattr(batch_panel_mod, "fluent_error", lambda *_args, **_kwargs: None)

    SectionParameterDialog._on_confirm(dialog)

    assert dialog.result is None
    assert errors == ["填写直墙高度 H直 时必须同时填写底宽 B"]
