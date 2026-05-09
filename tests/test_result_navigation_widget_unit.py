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


def _visible_chip_columns(bar, limit=10):
    return {chip.geometry().x() for chip in bar.chips()[:limit] if chip.isVisible()}


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
    assert wrapped_height == single_row_height
    assert wrapped_height < 140

    wide_bar.deleteLater()
    narrow_bar.deleteLater()


def test_case_result_navigation_bar_compacts_thirty_items_to_two_rows_then_scrolls():
    _get_qapp()
    mod = importlib.import_module("app_渠系计算前端.result_navigation")
    items = [
        {
            "case_idx": idx,
            "label": f"U形 · Q={35 - idx * 0.7:.1f}",
            "summary": f"U形 · Q={35 - idx * 0.7:.3f}",
            "is_error": False,
        }
        for idx in range(30)
    ]

    bar = mod.CaseResultNavigationBar()
    bar.resize(900, 500)
    bar.set_items(items)
    bar.show()
    _flush_events(6)

    collapsed_height = bar.height()
    assert bar.chip_count() == 30
    assert bar.chips()[0].text() == "工况1  Q=35.000"
    assert "U形" not in bar.chips()[0].text()
    assert bar.can_collapse() is True
    assert bar.is_expanded() is False
    assert collapsed_height < 180

    bar.set_expanded(True)
    _flush_events(6)

    expanded_height = bar.height()
    assert bar.is_expanded() is True
    assert expanded_height > collapsed_height
    assert expanded_height < 280
    assert bar._chip_scroll.verticalScrollBar().maximum() > 0

    bar.deleteLater()


def test_case_result_navigation_bar_resyncs_when_viewport_grows_without_bar_resize():
    _get_qapp()
    mod = importlib.import_module("app_渠系计算前端.result_navigation")
    items = [
        {
            "case_idx": idx,
            "label": f"工况 {idx + 1}",
            "summary": f"U形 · Q={35 - idx * 0.5:.3f}",
            "is_error": False,
        }
        for idx in range(10)
    ]

    bar = mod.CaseResultNavigationBar()
    bar.resize(420, 300)
    bar.set_items(items)
    bar.show()
    _flush_events(6)
    narrow_host_width = bar._chip_host.width()

    bar._chip_scroll.resize(900, bar._chip_scroll.height())
    _flush_events(6)

    viewport_width = bar._chip_scroll.viewport().width()
    assert viewport_width > narrow_host_width
    assert bar._chip_host.width() >= viewport_width - 4
    assert len(_visible_chip_columns(bar, limit=6)) >= 3

    bar.deleteLater()


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
    assert bar.chips()[0].text() == "工况1  Q=5.000"
    assert bar.chips()[0].toolTip() == "工况 1\n圆形 · Q=5.000"
    assert bar.chips()[1].property("resultNavError") is True
    assert bar.chips()[1].text() == "工况8  计算失败"
    assert "#C62828" in bar.chips()[1].styleSheet()

    bar.chips()[0].click()
    bar.chips()[1].click()

    assert requested == [0, 7]

    bar.deleteLater()


def test_case_result_state_helpers_distinguish_fresh_stale_and_empty_results():
    mod = importlib.import_module("app_渠系计算前端.result_navigation")

    assert mod.has_fresh_case_results(
        all_results=[(0, {"Q": 1.0}, {"success": True})],
        has_rendered_results=True,
        results_dirty=False,
    ) is True

    assert mod.has_fresh_case_results(
        all_results=[],
        has_rendered_results=True,
        results_dirty=False,
    ) is False
    assert mod.has_fresh_case_results(
        all_results=[(0, {"Q": 1.0}, {"success": True})],
        has_rendered_results=False,
        results_dirty=False,
    ) is False
    assert mod.has_fresh_case_results(
        all_results=[(0, {"Q": 1.0}, {"success": True})],
        has_rendered_results=True,
        results_dirty=True,
    ) is False


def test_case_result_jump_hint_text_explains_stale_results_can_be_recalculated_together():
    mod = importlib.import_module("app_渠系计算前端.result_navigation")

    stale_title, stale_content = mod.case_result_jump_hint(stale=True)
    structure_title, structure_content = mod.case_result_jump_hint(reason="structure_stale")
    empty_title, empty_content = mod.case_result_jump_hint(stale=False)

    assert stale_title == "结果已过期"
    assert stale_content == "因当前工况参数被修改，致使计算结果过期。请执行计算后再查看计算结果。"
    assert structure_title == "结果已失效"
    assert structure_content == "工况已删除，原计算结果与当前工况序号可能不一致。请执行计算后再查看计算结果。"
    assert empty_title == "暂无计算结果"
    assert "完成计算" in empty_content


def test_case_result_state_helpers_allow_fresh_case_when_another_case_is_stale():
    mod = importlib.import_module("app_渠系计算前端.result_navigation")
    all_results = [
        (0, {"Q": 5.0}, {"success": True}),
        (1, {"Q": 6.0}, {"success": True}),
        (2, {"Q": 7.0}, {"success": True}),
    ]

    assert mod.has_fresh_case_results(
        all_results=all_results,
        has_rendered_results=True,
        results_dirty=True,
        case_idx=0,
        stale_case_indexes={1},
    ) is True
    assert mod.has_fresh_case_results(
        all_results=all_results,
        has_rendered_results=True,
        results_dirty=True,
        case_idx=1,
        stale_case_indexes={1},
    ) is False
    assert mod.has_fresh_case_results(
        all_results=all_results,
        has_rendered_results=True,
        results_dirty=True,
        case_idx=0,
        stale_case_indexes={1},
        all_results_stale=True,
    ) is False
