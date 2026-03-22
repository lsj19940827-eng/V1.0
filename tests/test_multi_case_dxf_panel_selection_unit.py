# -*- coding: utf-8 -*-
"""Regression tests for panel-side DXF case selection helpers."""

import importlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

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


def _load_panel_class(folder: str, class_name: str):
    module = importlib.import_module(f"app_渠系计算前端.{folder}.panel")
    return getattr(module, class_name)


@pytest.mark.parametrize(
    ("folder", "class_name", "all_results", "current_case_idx", "expected_q"),
    [
        (
            "tunnel",
            "TunnelPanel",
            [
                {"input": {"section_type": "圆形", "Q": 10.0}, "result": {"success": True}},
                {"input": {"section_type": "圆形", "Q": 20.0}, "result": {"success": True}},
                {"input": {"section_type": "圆拱直墙型", "Q": 30.0}, "result": {"success": True}},
            ],
            1,
            20.0,
        ),
        (
            "open_channel",
            "OpenChannelPanel",
            [
                (2, {"section_type": "梯形", "Q": 30.0}, {"success": True}),
                (0, {"section_type": "梯形", "Q": 10.0}, {"success": True}),
                (1, {"section_type": "梯形", "Q": 20.0}, {"success": True}),
            ],
            1,
            20.0,
        ),
        (
            "aqueduct",
            "AqueductPanel",
            [
                (1, {"section_type": "矩形", "Q": 20.0}, {"success": True}),
                (2, {"section_type": "矩形", "Q": 30.0}, {"success": True}),
                (0, {"section_type": "矩形", "Q": 10.0}, {"success": True}),
            ],
            2,
            30.0,
        ),
        (
            "culvert",
            "CulvertPanel",
            [
                (1, {"Q": 20.0}, {"success": True}),
                (0, {"Q": 10.0}, {"success": True}),
                (2, {"Q": 30.0}, {"success": True}),
            ],
            1,
            20.0,
        ),
    ],
)
def test_panel_dxf_current_entry_uses_left_selected_case(folder, class_name, all_results, current_case_idx, expected_q):
    panel_cls = _load_panel_class(folder, class_name)
    dummy = SimpleNamespace(
        _cases=[{"custom_label": ""}, {"custom_label": ""}, {"custom_label": ""}],
        _all_results=all_results,
        _current_case_idx=current_case_idx,
        _results_dirty=False,
        _case_label=lambda case, idx: f"工况 {idx + 1}",
    )

    entries = panel_cls._build_dxf_export_case_entries(dummy)
    current_entry = panel_cls._get_current_dxf_export_entry(dummy, entries)

    assert current_entry is not None
    assert current_entry.case_idx == current_case_idx
    assert current_entry.input_params["Q"] == expected_q


@pytest.mark.parametrize(
    ("folder", "class_name", "all_results"),
    [
        (
            "tunnel",
            "TunnelPanel",
            [{"input": {"section_type": "圆形", "Q": 10.0}, "result": {"success": True}}],
        ),
        (
            "open_channel",
            "OpenChannelPanel",
            [(0, {"section_type": "梯形", "Q": 10.0}, {"success": True})],
        ),
        (
            "aqueduct",
            "AqueductPanel",
            [(0, {"section_type": "矩形", "Q": 10.0}, {"success": True})],
        ),
        (
            "culvert",
            "CulvertPanel",
            [(0, {"Q": 10.0}, {"success": True})],
        ),
    ],
)
def test_panel_dxf_entries_mark_cached_results_stale_when_dirty(folder, class_name, all_results):
    panel_cls = _load_panel_class(folder, class_name)
    dummy = SimpleNamespace(
        _cases=[{"custom_label": ""}, {"custom_label": ""}],
        _all_results=all_results,
        _current_case_idx=0,
        _results_dirty=True,
        _case_label=lambda case, idx: f"工况 {idx + 1}",
    )

    entries = panel_cls._build_dxf_export_case_entries(dummy)

    assert len(entries) == 2
    assert all(entry.is_valid is False for entry in entries)
    assert all(entry.invalid_reason == "结果已失效" for entry in entries)
