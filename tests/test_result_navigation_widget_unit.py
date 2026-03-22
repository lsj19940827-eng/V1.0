# -*- coding: utf-8 -*-
"""Unit tests for the desktop-native result case navigation bar."""

import importlib
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 3):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def test_case_result_navigation_bar_hides_for_empty_and_single_case_items():
    _get_qapp()
    mod = importlib.import_module("app_渠系计算前端.result_navigation")
    bar = mod.CaseResultNavigationBar()

    bar.set_items([])
    assert bar.isVisible() is False
    assert bar.chip_count() == 0

    bar.set_items(
        [
            {
                "case_idx": 3,
                "label": "工况 4",
                "summary": "Q=4.000",
                "is_error": False,
            }
        ]
    )
    assert bar.isVisible() is False
    assert bar.chip_count() == 0

    bar.deleteLater()


def test_case_result_navigation_bar_shrinks_to_content_height_and_rewraps():
    _get_qapp()
    mod = importlib.import_module("app_渠系计算前端.result_navigation")
    items = [
        {
            "case_idx": idx,
            "label": f"工况 {idx + 1}",
            "summary": "矩形 · Q=10.000",
            "is_error": False,
        }
        for idx in range(6)
    ]

    wide_bar = mod.CaseResultNavigationBar()
    wide_bar.resize(1200, 400)
    wide_bar.set_items(items)
    wide_bar.show()
    _flush_events(4)
    single_row_height = wide_bar.height()

    assert single_row_height == wide_bar.sizeHint().height()
    assert single_row_height < 140

    narrow_bar = mod.CaseResultNavigationBar()
    narrow_bar.resize(650, 400)
    narrow_bar.set_items(items)
    narrow_bar.show()
    _flush_events(4)
    wrapped_height = narrow_bar.height()

    assert wrapped_height == narrow_bar.sizeHint().height()
    assert wrapped_height > single_row_height
    assert wrapped_height < 320

    wide_bar.deleteLater()
    narrow_bar.deleteLater()


def test_case_result_navigation_bar_renders_multiple_items_and_emits_case_idx():
    _get_qapp()
    mod = importlib.import_module("app_渠系计算前端.result_navigation")
    bar = mod.CaseResultNavigationBar()
    requested = []
    bar.case_requested.connect(requested.append)

    bar.set_items(
        [
            {
                "label": "工况 1",
                "summary": "圆形 · Q=5.000",
                "is_error": False,
            },
            {
                "case_idx": 7,
                "label": "工况 8",
                "summary": "计算失败",
                "is_error": True,
            },
        ]
    )

    assert bar.isVisible() is True
    assert bar.chip_count() == 2
    assert "圆形" in bar.chips()[0].text()
    assert bar.chips()[1].property("resultNavError") is True
    assert "#C62828" in bar.chips()[1].styleSheet()

    bar.chips()[0].click()
    bar.chips()[1].click()

    assert requested == [0, 7]

    bar.deleteLater()
