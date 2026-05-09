# -*- coding: utf-8 -*-
"""UI regression tests for shared multi-case components."""

import importlib.util
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

from PySide6.QtWidgets import QApplication


def _load_case_manager_module():
    module_path = next(Path(".").glob("app_*/case_manager.py")).resolve()
    spec = importlib.util.spec_from_file_location("case_manager_ui_test_module", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CASE_MANAGER = _load_case_manager_module()
CaseTagNavigator = _CASE_MANAGER.CaseTagNavigator
CaseWorkbenchStrip = _CASE_MANAGER.CaseWorkbenchStrip


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _make_case(q_value: str, custom_label=None):
    return {
        "custom_label": custom_label,
        "section_type": "梯形",
        "Q": q_value,
    }


def _label_for(case):
    q_text = (case.get("Q", "") or "").strip() or "?"
    title = case.get("custom_label") or case.get("section_type", "梯形")
    return f"{title} · Q={q_text}"


def _view_getter(case, idx):
    label = _label_for(case)
    return {"label": label, "tooltip": f"{label}\n设计流量 Q={case['Q']} m³/s"}


def test_case_tag_navigator_collapses_after_three_rows_and_expands_without_internal_scroll():
    _get_qapp()
    nav = CaseTagNavigator()
    nav.resize(240, 240)
    nav.show()

    cases = [_make_case(str(i), f"上游方案-{i}") for i in range(1, 9)]
    nav.sync_cases(cases, 5, _view_getter)
    _flush_events(6)

    collapsed_height = nav.height()

    assert nav.chip_count() == 8
    assert nav.case_labels() == [_label_for(case) for case in cases]
    assert nav.can_collapse() is True
    assert nav.is_expanded() is False

    nav.set_expanded(True)
    _flush_events(6)

    assert nav.is_expanded() is True
    assert nav.height() > collapsed_height

    long_case = _make_case("12.6", "上游衔接断面-考虑检修期高水位组合校核")
    nav.sync_cases([long_case], 0, _view_getter)
    _flush_events(6)

    assert nav.chip_count() == 1
    assert nav.case_labels() == [_label_for(long_case)]
    assert nav._chips[0].width() <= nav._chips[0].maximumWidth()

    nav.deleteLater()


def test_case_workbench_strip_exposes_meta_controls_and_remove_state():
    _get_qapp()
    strip = CaseWorkbenchStrip()
    strip.resize(320, 260)
    strip.show()

    cases = [_make_case(str(i), f"上游方案-{i}") for i in range(1, 9)]
    strip.sync_cases(cases, 2, _view_getter)
    strip.set_remove_enabled(True)
    _flush_events(6)

    assert strip.chip_count() == 8
    assert strip.can_collapse() is True
    assert strip._count_label.text() == "8 个计算工况"
    assert strip._toggle_button.isVisible() is True
    assert strip._remove_button.isEnabled() is True

    strip.set_expanded(True)
    _flush_events(6)

    assert strip.is_expanded() is True
    assert strip._toggle_button.text() == "收起"

    strip.set_remove_enabled(False)
    _flush_events()

    assert strip._remove_button.isEnabled() is False

    strip.deleteLater()


def test_manual_case_limits_are_raised_to_thirty():
    pressure_pipe = __import__(
        "app_渠系计算前端.pressure_pipe.panel",
        fromlist=["MAX_CASES"],
    )

    assert _CASE_MANAGER.MAX_CASES == 30
    assert pressure_pipe.MAX_CASES == 30


def test_case_workbench_strip_reflows_new_last_chip_without_waiting_for_next_add():
    _get_qapp()
    strip = CaseWorkbenchStrip()
    strip.resize(520, 220)
    strip.show()

    active_style = _CASE_MANAGER.CASE_TAG_ACTIVE_SS

    for count in range(3, 7):
        cases = [{"label": f"Case {idx + 1}", "tooltip": f"Case {idx + 1}"} for idx in range(count)]
        strip.sync_cases(cases, count - 1, lambda case, idx: case)
        _flush_events(6)

        chips = strip.navigator()._chips
        geometries = [
            (chip.geometry().x(), chip.geometry().y(), chip.geometry().width(), chip.geometry().height())
            for chip in chips
        ]
        active_indexes = [idx for idx, chip in enumerate(chips) if chip.styleSheet() == active_style]

        assert strip.chip_count() == count
        assert len(geometries) == count
        assert active_indexes == [count - 1]
        assert geometries[-1] != geometries[0]

        if count == 4:
            assert geometries[-1][1] == 0
        if count == 5:
            assert geometries[-1][1] > geometries[0][1]
        if count == 6:
            assert geometries[-1][1] == geometries[-2][1]
            assert geometries[-1][0] > geometries[-2][0]

    strip.deleteLater()


def test_case_workbench_strip_prefers_compact_labels_for_three_columns():
    _get_qapp()
    strip = CaseWorkbenchStrip()
    strip.resize(420, 240)
    strip.show()

    cases = [_make_case(str(idx + 1), f"很长的工况名称-{idx + 1}") for idx in range(6)]

    def _compact_view(case, idx):
        full_label = _label_for(case)
        return {
            "label": full_label,
            "compact_label": f"{idx + 1}｜Q={case['Q']}",
            "tooltip": f"{full_label}\n断面类型：{case['section_type']}",
        }

    strip.sync_cases(cases, 0, _compact_view)
    _flush_events(6)

    chips = strip.navigator()._chips
    geometries = [(chip.geometry().x(), chip.geometry().y()) for chip in chips]
    visible_texts = [chip.text() for chip in chips]

    assert strip.case_labels() == [_label_for(case) for case in cases]
    assert visible_texts == [f"{idx + 1}｜Q={idx + 1}" for idx in range(6)]
    assert [geo[1] for geo in geometries[:3]] == [geometries[0][1]] * 3
    assert geometries[3][1] > geometries[0][1]
    assert chips[0].toolTip().startswith("很长的工况名称-1")

    strip.deleteLater()
