# -*- coding: utf-8 -*-
"""有压管道面板项目保存的 JSON 安全性测试。"""

from dataclasses import dataclass
import json
from types import SimpleNamespace

from app_渠系计算前端.pressure_pipe import panel as pressure_pipe_panel_mod

PressurePipePanel = pressure_pipe_panel_mod.PressurePipePanel


@dataclass
class _NestedPayload:
    """构造包含多层非有限浮点数的测试数据。"""

    flow: float
    detail: dict
    values: list


def test_dataclass_or_object_dict_converts_non_finite_numbers_to_none_for_strict_json():
    """递归转换 dataclass、dict、list 中的非有限浮点数。"""
    payload = _NestedPayload(
        flow=float("nan"),
        detail={"head_loss": float("inf"), "ok": 1.25},
        values=[float("-inf"), {"nested": float("nan")}],
    )

    data = PressurePipePanel._dataclass_or_object_dict(payload)

    assert data == {
        "flow": None,
        "detail": {"head_loss": None, "ok": 1.25},
        "values": [None, {"nested": None}],
    }
    json.dumps(data, ensure_ascii=False, allow_nan=False)


def test_to_project_dict_converts_non_finite_numbers_to_none_for_strict_json():
    """完整项目保存输出中不保留 NaN 和 Infinity。"""
    panel = PressurePipePanel.__new__(PressurePipePanel)
    panel._save_current_case = lambda: None
    panel._cases = [
        {
            "Q": float("nan"),
            "nested": {"slope": float("inf")},
            "values": [float("-inf")],
        }
    ]
    panel._current_case_idx = 0
    panel._last_errors = []
    panel._all_results = [
        (
            0,
            SimpleNamespace(Q=float("inf"), nested={"x": float("nan")}),
            SimpleNamespace(
                recommended={"D": float("-inf")},
                top_candidates=[{"hf": float("inf")}],
                category="推荐",
                reason="",
                calc_steps="",
                auto_recommended=None,
            ),
        )
    ]
    panel.current_result = SimpleNamespace(
        recommended=SimpleNamespace(D=float("nan")),
        top_candidates=[SimpleNamespace(v=float("inf"))],
        category="当前",
        reason="",
        calc_steps="",
        auto_recommended=None,
    )
    panel._export_plain_text = "结果文本"
    panel._results_dirty = False
    panel._stale_result_case_indexes = set()
    panel._all_results_stale = False
    panel._has_rendered_results = True

    data = panel.to_project_dict()

    assert data["cases"][0]["Q"] is None
    assert data["cases"][0]["nested"]["slope"] is None
    assert data["cases"][0]["values"] == [None]
    assert data["all_results"][0]["input"]["data"]["Q"] is None
    assert data["all_results"][0]["result"]["recommended"]["D"] is None
    assert data["current_result"]["recommended"]["D"] is None
    json.dumps(data, ensure_ascii=False, allow_nan=False)


def test_display_all_results_suppresses_fresh_jump_during_project_restore(monkeypatch):
    """项目恢复显示结果时，不应先按新鲜结果自动跳转。"""
    panel = PressurePipePanel.__new__(PressurePipePanel)
    panel._all_results = [
        (
            0,
            SimpleNamespace(Q=5.0),
            SimpleNamespace(recommended=None, calc_steps="", reason="无推荐"),
        )
    ]
    panel._panel_key = "pressure-pipe"
    panel._case_result_nav_label = lambda _idx: "工况 1"
    panel._build_result_card_html = lambda *_args: "<p>结果</p>"
    panel.detail_cb = SimpleNamespace(isChecked=lambda: False)
    panel.result_view = object()
    panel._result_case_nav = object()
    calls = []
    panel.notebook = SimpleNamespace(setCurrentIndex=lambda index: calls.append(("tab", index)))
    panel._mark_results_fresh = lambda: calls.append(("fresh", None))
    panel._jump_to_case_result = lambda idx, defer_until_load=False: calls.append(("jump", idx))
    panel._current_case_idx = 0
    panel._suppress_project_restore_side_effects = True
    monkeypatch.setattr(pressure_pipe_panel_mod, "load_formula_page", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pressure_pipe_panel_mod, "sync_case_result_nav_bar", lambda *_args, **_kwargs: None)

    PressurePipePanel._display_all_results(panel)

    assert calls == []
