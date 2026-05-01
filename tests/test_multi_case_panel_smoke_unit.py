# -*- coding: utf-8 -*-
"""Smoke tests for shared multi-case navigator integration in real panels."""

import importlib
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

from PySide6.QtWidgets import QApplication


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_panel_class(folder: str, class_name: str):
    module = _load_panel_module(folder)
    return getattr(module, class_name)


def _load_panel_module(folder: str):
    webview_compat = importlib.import_module("app_渠系计算前端.webview_compat")
    webview_compat._QtWebEngineView = None
    webview_compat._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view in smoke test")
    module = importlib.import_module(f"app_渠系计算前端.{folder}.panel")
    if hasattr(module, "QWebEngineView"):
        module.QWebEngineView = None
        module._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view in smoke test")
    return module


PANEL_NAV_SCENARIOS = [
    (
        "open_channel",
        "OpenChannelPanel",
        [
            (0, {"section_type": "梯形", "Q": 1.0}, {"success": True}),
            (1, {"section_type": "矩形", "Q": 2.0}, {"success": True}),
        ],
        "case-result-open-channel-1",
    ),
    (
        "aqueduct",
        "AqueductPanel",
        [
            (0, {"section_type": "U形", "Q": 1.0}, {"success": True}),
            (1, {"section_type": "矩形", "Q": 2.0}, {"success": True}),
        ],
        "case-result-aqueduct-1",
    ),
    (
        "culvert",
        "CulvertPanel",
        [
            (0, {"section_type": "矩形", "Q": 1.0}, {"success": True}),
            (1, {"section_type": "圆拱直墙型", "Q": 2.0}, {"success": True}),
        ],
        "case-result-culvert-1",
    ),
    (
        "tunnel",
        "TunnelPanel",
        [
            {
                "input": {"section_type": "圆形", "Q": 1.0},
                "result": {"success": True},
                "case": {"section_type": "圆形", "Q": "1"},
            },
            {
                "input": {"section_type": "圆拱直墙型", "Q": 2.0},
                "result": {"success": True},
                "case": {"section_type": "圆拱直墙型", "Q": "2"},
            },
        ],
        "case-result-tunnel-1",
    ),
    (
        "pressure_pipe",
        "PressurePipePanel",
        [
            (0, {"Q": 1.0}, {"success": True}),
            (1, {"Q": 2.0}, {"success": True}),
        ],
        "case-result-pressure-pipe-1",
    ),
]

PANEL_NAV_THREE_CASE_SCENARIOS = [
    (
        "open_channel",
        "OpenChannelPanel",
        [
            (0, {"section_type": "梯形", "Q": 5.0}, {"success": True}),
            (1, {"section_type": "矩形", "Q": 6.0}, {"success": True}),
            (2, {"section_type": "圆形", "Q": 7.0}, {"success": True}),
        ],
        ("case-result-open-channel-0", "case-result-open-channel-2"),
    ),
    (
        "aqueduct",
        "AqueductPanel",
        [
            (0, {"section_type": "U形", "Q": 5.0}, {"success": True}),
            (1, {"section_type": "矩形", "Q": 6.0}, {"success": True}),
            (2, {"section_type": "U形", "Q": 7.0}, {"success": True}),
        ],
        ("case-result-aqueduct-0", "case-result-aqueduct-2"),
    ),
    (
        "culvert",
        "CulvertPanel",
        [
            (0, {"section_type": "矩形", "Q": 5.0}, {"success": True}),
            (1, {"section_type": "圆拱直墙型", "Q": 6.0}, {"success": True}),
            (2, {"section_type": "矩形", "Q": 7.0}, {"success": True}),
        ],
        ("case-result-culvert-0", "case-result-culvert-2"),
    ),
    (
        "tunnel",
        "TunnelPanel",
        [
            {
                "input": {"section_type": "圆形", "Q": 5.0},
                "result": {"success": True},
                "case": {"section_type": "圆形", "Q": "5"},
            },
            {
                "input": {"section_type": "圆拱直墙型", "Q": 6.0},
                "result": {"success": True},
                "case": {"section_type": "圆拱直墙型", "Q": "6"},
            },
            {
                "input": {"section_type": "圆形", "Q": 7.0},
                "result": {"success": True},
                "case": {"section_type": "圆形", "Q": "7"},
            },
        ],
        ("case-result-tunnel-0", "case-result-tunnel-2"),
    ),
    (
        "pressure_pipe",
        "PressurePipePanel",
        [
            (0, {"Q": 5.0}, {"success": True}),
            (1, {"Q": 6.0}, {"success": True}),
            (2, {"Q": 7.0}, {"success": True}),
        ],
        ("case-result-pressure-pipe-0", "case-result-pressure-pipe-2"),
    ),
]


def _make_panel_for_nav_case(module, class_name):
    panel = getattr(module, class_name)()
    panel.resize(1366, 900)
    panel.show()
    _flush_events(6)
    if len(getattr(panel, "_cases", [])) < 2:
        panel._add_case()
        _flush_events(4)
    return panel


def _ensure_case_count(panel, target_count):
    while len(getattr(panel, "_cases", [])) < target_count:
        panel._add_case()
        _flush_events(4)


def _prime_three_case_results(panel, fake_results):
    panel._all_results = fake_results
    panel._has_rendered_results = True
    panel._results_dirty = False
    panel._stale_result_case_indexes = set()
    panel._all_results_stale = False


def _install_nav_spies(monkeypatch, module):
    warnings = []
    scroll_calls = []

    class InfoBarSpy:
        @classmethod
        def warning(cls, *args, **kwargs):
            warnings.append(kwargs)

        @classmethod
        def success(cls, *args, **kwargs):
            pass

        @classmethod
        def error(cls, *args, **kwargs):
            pass

    def _spy_scroll(*args, **kwargs):
        scroll_calls.append((args, kwargs))
        return True

    monkeypatch.setattr(module, "InfoBar", InfoBarSpy)
    monkeypatch.setattr(module, "scroll_view_to_anchor", _spy_scroll)
    return warnings, scroll_calls


def test_open_channel_panel_places_case_strip_above_input_group_and_refreshes_labels():
    _get_qapp()
    panel_cls = _load_panel_class("open_channel", "OpenChannelPanel")
    panel = panel_cls()
    panel.resize(1366, 900)
    panel.show()
    _flush_events(6)

    assert hasattr(panel, "_case_strip")
    assert panel._case_strip.y() < panel._input_group.y()

    panel.m_edit.setText("2.5")
    panel._save_current_case()
    panel._add_case()
    _flush_events()

    assert panel._cases[-1]["Q"] == ""
    assert panel._cases[-1]["m"] == "2.5"

    for idx in range(2, 7):
        panel.Q_edit.setText(str(idx))
        _flush_events()
        if idx < 6:
            panel._add_case()
            _flush_events()

    labels_before = list(panel._case_strip.case_labels())
    panel._switch_case(2)
    panel.Q_edit.setText("99")
    _flush_events()
    labels_after = list(panel._case_strip.case_labels())

    assert panel._case_strip.chip_count() == 6
    assert labels_before[:2] == labels_after[:2]
    assert labels_before[3:] == labels_after[3:]
    assert "Q=99" in labels_after[2]
    assert "|" not in labels_after[2]

    panel._remove_current_case()
    _flush_events()

    assert panel._case_strip.chip_count() == 5

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_pressure_pipe_panel_uses_external_case_strip_and_supports_custom_labels():
    _get_qapp()
    panel_cls = _load_panel_class("pressure_pipe", "PressurePipePanel")
    panel = panel_cls()
    panel.resize(1366, 900)
    panel.show()
    _flush_events(6)

    assert hasattr(panel, "_case_strip")
    assert panel._case_strip.y() < panel._input_group.y()

    panel.length_edit.setText("1500")
    panel._save_current_case()
    panel._add_case()
    _flush_events()

    assert panel._cases[-1]["Q"] == ""
    assert panel._cases[-1]["length"] == "1500"

    for idx in range(2, 7):
        panel.Q_edit.setText(str(idx / 10))
        _flush_events()
        if idx < 6:
            panel._add_case()
            _flush_events()

    panel._on_case_renamed(1, "方案B")
    _flush_events()

    labels = panel._case_strip.case_labels()

    assert panel._case_strip.chip_count() == 6
    assert labels[1].startswith("方案B · Q=")
    assert "L=" not in labels[1]
    assert panel._case_strip._remove_button.isEnabled() is True

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_pressure_pipe_panel_defers_initial_help_render_until_first_show(monkeypatch):
    _get_qapp()
    panel_cls = _load_panel_class("pressure_pipe", "PressurePipePanel")
    calls = []

    def _fake_show_initial_help(self):
        calls.append("initial-help")

    monkeypatch.setattr(panel_cls, "_show_initial_help", _fake_show_initial_help)

    panel = panel_cls()

    assert calls == []

    panel.resize(1366, 900)
    panel.show()
    _flush_events(6)

    assert calls == ["initial-help"]

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_open_channel_panel_keeps_last_added_chip_visible_and_active_during_incremental_adds():
    _get_qapp()
    panel_cls = _load_panel_class("open_channel", "OpenChannelPanel")
    panel = panel_cls()
    panel.resize(1366, 900)
    panel.show()
    _flush_events(6)

    for expected_count in range(2, 7):
        panel.Q_edit.setText(str(expected_count))
        _flush_events()
        panel._add_case()
        _flush_events(6)

        chips = panel._case_strip.navigator()._chips
        geometries = [
            (chip.geometry().x(), chip.geometry().y(), chip.geometry().width(), chip.geometry().height())
            for chip in chips
        ]
        active_indexes = [
            idx for idx, chip in enumerate(chips) if "#0E5DB8" in chip.styleSheet()
        ]

        assert panel._case_strip.chip_count() == expected_count
        assert len(geometries) == expected_count
        assert active_indexes == [expected_count - 1]

        if expected_count >= 4:
            assert geometries[-1] != geometries[0]

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_pressure_pipe_result_case_nav_bar_is_visible_and_clicks_reuse_anchor_jump():
    _get_qapp()
    webview_compat = importlib.import_module("app_渠系计算前端.webview_compat")
    webview_compat._QtWebEngineView = None
    webview_compat._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view in smoke test")
    module = importlib.import_module("app_渠系计算前端.pressure_pipe.panel")
    module.QWebEngineView = None
    module._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view in smoke test")

    scroll_calls = []

    def _spy_scroll(*args, **kwargs):
        scroll_calls.append((args, kwargs))
        return True

    module.scroll_view_to_anchor = _spy_scroll

    panel = module.PressurePipePanel()
    panel.resize(1366, 900)
    panel.show()
    _flush_events(6)

    panel.Q_edit.setText("0.8")
    _flush_events()
    panel._add_case()
    _flush_events()
    panel._switch_case(1)
    _flush_events()
    panel.Q_edit.setText("1.2")
    _flush_events()

    panel._calc_btn.click()
    _flush_events(8)

    assert panel._result_case_nav.isVisible() is True
    assert panel._result_case_nav.chip_count() == 2
    assert panel._result_case_nav.height() == panel._result_case_nav.sizeHint().height()
    assert panel._result_case_nav.height() < 120

    scroll_calls.clear()
    panel._result_case_nav.chips()[1].click()
    _flush_events(2)

    assert scroll_calls
    assert scroll_calls[-1][0][1] == "case-result-pressure-pipe-1"

    panel.close()
    panel.deleteLater()
    _flush_events(4)


@pytest.mark.parametrize(
    ("folder", "class_name", "fake_results", "expected_anchor"),
    PANEL_NAV_SCENARIOS,
)
def test_left_case_tags_switch_without_warning_until_results_are_fresh(
    monkeypatch, folder, class_name, fake_results, expected_anchor
):
    _get_qapp()
    module = _load_panel_module(folder)
    warnings, scroll_calls = _install_nav_spies(monkeypatch, module)

    panel = _make_panel_for_nav_case(module, class_name)
    try:
        panel._all_results = []
        panel._has_rendered_results = False
        panel._results_dirty = False
        panel._switch_case(1)
        _flush_events(2)

        assert panel._current_case_idx == 1
        assert warnings == []
        assert scroll_calls == []

        panel._switch_case(0)
        _flush_events(2)
        warnings.clear()
        scroll_calls.clear()
        panel._all_results = fake_results
        panel._has_rendered_results = True
        panel._results_dirty = True
        panel._stale_result_case_indexes = {1}
        panel._all_results_stale = False
        panel._switch_case(1)
        _flush_events(2)

        assert panel._current_case_idx == 1
        assert warnings == []
        assert scroll_calls == []

        panel._switch_case(0)
        _flush_events(2)
        warnings.clear()
        scroll_calls.clear()
        panel._all_results = fake_results
        panel._has_rendered_results = True
        panel._results_dirty = False
        panel._switch_case(1)
        _flush_events(2)

        assert panel._current_case_idx == 1
        assert warnings == []
        assert scroll_calls
        assert scroll_calls[-1][0][1] == expected_anchor
    finally:
        panel.close()
        panel.deleteLater()
        _flush_events(4)


@pytest.mark.parametrize(
    ("folder", "class_name", "fake_results", "expected_anchor"),
    PANEL_NAV_SCENARIOS,
)
def test_right_result_nav_warns_for_stale_results_and_jumps_for_fresh_results(
    monkeypatch, folder, class_name, fake_results, expected_anchor
):
    _get_qapp()
    module = _load_panel_module(folder)
    warnings, scroll_calls = _install_nav_spies(monkeypatch, module)

    panel = _make_panel_for_nav_case(module, class_name)
    try:
        panel._all_results = fake_results
        panel._has_rendered_results = True
        panel._results_dirty = True
        panel._stale_result_case_indexes = {1}
        panel._all_results_stale = False
        panel._result_case_nav.set_items(panel._build_case_nav_items())
        _flush_events(4)

        panel._result_case_nav.chips()[1].click()
        _flush_events(2)

        assert scroll_calls == []
        assert warnings
        assert warnings[-1]["title"] == "结果已过期"
        assert warnings[-1]["content"] == (
            "因当前工况参数被修改，致使计算结果过期。请执行计算后再查看计算结果。"
        )

        warnings.clear()
        scroll_calls.clear()
        panel._results_dirty = False
        panel._stale_result_case_indexes = set()
        panel._result_case_nav.chips()[1].click()
        _flush_events(2)

        assert warnings == []
        assert scroll_calls
        assert scroll_calls[-1][0][1] == expected_anchor
    finally:
        panel.close()
        panel.deleteLater()
        _flush_events(4)


@pytest.mark.parametrize(
    ("folder", "class_name", "fake_results", "expected_anchors"),
    PANEL_NAV_THREE_CASE_SCENARIOS,
)
def test_result_nav_only_blocks_the_case_whose_inputs_changed(
    monkeypatch, folder, class_name, fake_results, expected_anchors
):
    _get_qapp()
    module = _load_panel_module(folder)
    warnings, scroll_calls = _install_nav_spies(monkeypatch, module)

    panel = _make_panel_for_nav_case(module, class_name)
    try:
        _ensure_case_count(panel, 3)
        panel._all_results = fake_results
        panel._has_rendered_results = True
        panel._results_dirty = True
        panel._stale_result_case_indexes = {1}
        panel._all_results_stale = False
        panel._result_case_nav.set_items(panel._build_case_nav_items())
        _flush_events(4)

        panel._result_case_nav.chips()[0].click()
        _flush_events(2)
        panel._result_case_nav.chips()[2].click()
        _flush_events(2)

        assert warnings == []
        assert [call[0][1] for call in scroll_calls] == list(expected_anchors)

        scroll_calls.clear()
        panel._result_case_nav.chips()[1].click()
        _flush_events(2)

        assert scroll_calls == []
        assert warnings
        assert warnings[-1]["title"] == "结果已过期"
        assert warnings[-1]["content"] == (
            "因当前工况参数被修改，致使计算结果过期。请执行计算后再查看计算结果。"
        )
    finally:
        panel.close()
        panel.deleteLater()
        _flush_events(4)


@pytest.mark.parametrize(
    ("folder", "class_name", "fake_results", "expected_anchors"),
    PANEL_NAV_THREE_CASE_SCENARIOS,
)
def test_left_case_tags_jump_for_fresh_cases_and_skip_stale_case_without_warning(
    monkeypatch, folder, class_name, fake_results, expected_anchors
):
    _get_qapp()
    module = _load_panel_module(folder)
    warnings, scroll_calls = _install_nav_spies(monkeypatch, module)

    panel = _make_panel_for_nav_case(module, class_name)
    try:
        _ensure_case_count(panel, 3)
        panel._all_results = fake_results
        panel._has_rendered_results = True
        panel._results_dirty = True
        panel._stale_result_case_indexes = {1}
        panel._all_results_stale = False

        panel._switch_case(2)
        _flush_events(2)

        assert panel._current_case_idx == 2
        assert warnings == []
        assert scroll_calls[-1][0][1] == expected_anchors[1]

        scroll_calls.clear()
        panel._switch_case(1)
        _flush_events(2)

        assert panel._current_case_idx == 1
        assert warnings == []
        assert scroll_calls == []
    finally:
        panel.close()
        panel.deleteLater()
        _flush_events(4)


@pytest.mark.parametrize(
    ("folder", "class_name", "fake_results", "expected_anchors"),
    PANEL_NAV_THREE_CASE_SCENARIOS,
)
def test_copy_to_all_marks_only_recipient_cases_stale(
    monkeypatch, folder, class_name, fake_results, expected_anchors
):
    _get_qapp()
    module = _load_panel_module(folder)
    warnings, scroll_calls = _install_nav_spies(monkeypatch, module)

    panel = _make_panel_for_nav_case(module, class_name)
    try:
        _ensure_case_count(panel, 3)
        _prime_three_case_results(panel, fake_results)
        panel._current_case_idx = 1
        panel._load_case(1)
        panel._apply_to_all_cases()
        panel._result_case_nav.set_items(panel._build_case_nav_items())
        _flush_events(4)

        assert panel._results_dirty is True
        assert panel._stale_result_case_indexes == {0, 2}
        assert panel._all_results_stale is False

        panel._result_case_nav.chips()[1].click()
        _flush_events(2)
        assert warnings == []
        assert scroll_calls[-1][0][1] == module.make_case_result_anchor(panel._panel_key, 1)

        scroll_calls.clear()
        panel._result_case_nav.chips()[0].click()
        _flush_events(2)
        panel._result_case_nav.chips()[2].click()
        _flush_events(2)

        assert scroll_calls == []
        assert warnings[-1]["title"] == "结果已过期"
        assert "请执行计算后再查看计算结果" in warnings[-1]["content"]
    finally:
        panel.close()
        panel.deleteLater()
        _flush_events(4)


@pytest.mark.parametrize(
    ("folder", "class_name", "fake_results", "expected_anchors"),
    PANEL_NAV_THREE_CASE_SCENARIOS,
)
def test_add_case_keeps_existing_result_nav_jumpable(
    monkeypatch, folder, class_name, fake_results, expected_anchors
):
    _get_qapp()
    module = _load_panel_module(folder)
    warnings, scroll_calls = _install_nav_spies(monkeypatch, module)

    panel = _make_panel_for_nav_case(module, class_name)
    try:
        _ensure_case_count(panel, 3)
        _prime_three_case_results(panel, fake_results)
        panel._add_case()
        panel._result_case_nav.set_items(panel._build_case_nav_items())
        _flush_events(4)

        assert len(panel._cases) == 4
        assert panel._results_dirty is True
        assert panel._stale_result_case_indexes == set()

        panel._result_case_nav.chips()[0].click()
        _flush_events(2)
        panel._result_case_nav.chips()[2].click()
        _flush_events(2)

        assert warnings == []
        assert [call[0][1] for call in scroll_calls] == list(expected_anchors)
    finally:
        panel.close()
        panel.deleteLater()
        _flush_events(4)


@pytest.mark.parametrize(
    ("folder", "class_name", "fake_results", "expected_anchors"),
    PANEL_NAV_THREE_CASE_SCENARIOS,
)
def test_delete_case_marks_all_old_result_nav_stale(
    monkeypatch, folder, class_name, fake_results, expected_anchors
):
    _get_qapp()
    module = _load_panel_module(folder)
    warnings, scroll_calls = _install_nav_spies(monkeypatch, module)

    panel = _make_panel_for_nav_case(module, class_name)
    try:
        _ensure_case_count(panel, 3)
        _prime_three_case_results(panel, fake_results)
        panel._current_case_idx = 1
        panel._load_case(1)
        panel._remove_current_case()
        panel._result_case_nav.set_items(panel._build_case_nav_items())
        _flush_events(4)

        assert len(panel._cases) == 2
        assert panel._results_dirty is True
        assert panel._all_results_stale is True

        panel._result_case_nav.chips()[0].click()
        _flush_events(2)

        assert scroll_calls == []
        assert warnings[-1]["title"] == "结果已失效"
        assert warnings[-1]["content"] == (
            "工况已删除，原计算结果与当前工况序号可能不一致。请执行计算后再查看计算结果。"
        )
    finally:
        panel.close()
        panel.deleteLater()
        _flush_events(4)
