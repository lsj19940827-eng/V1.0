# -*- coding: utf-8 -*-
"""6个设计面板“按Q加大输入”模式的回归测试。"""

import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
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

BASE_PACKAGE = "app_渠系计算前端"


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _find_tooltip_filter(widget):
    """查找控件上挂载的悬浮提示过滤器。"""
    for child in widget.children():
        if hasattr(child, "_tooltipDelay"):
            return child

    return None


def _force_fallback_webview():
    webview_compat = importlib.import_module(BASE_PACKAGE + ".webview_compat")
    webview_compat._QtWebEngineView = None
    webview_compat._WEB_ENGINE_IMPORT_ERROR = RuntimeError(
        "forced fallback web view in tests"
    )


def _load_panel_module(folder):
    _force_fallback_webview()
    module = importlib.import_module(f"{BASE_PACKAGE}.{folder}.panel")
    if hasattr(module, "QWebEngineView"):
        module.QWebEngineView = None
        module._WEB_ENGINE_IMPORT_ERROR = RuntimeError(
            "forced fallback web view in tests"
        )
    return module


def _new_panel(folder, class_name):
    _get_qapp()
    module = _load_panel_module(folder)
    panel_cls = getattr(module, class_name)
    if folder == "siphon" and class_name == "SiphonPanel":
        panel = panel_cls(show_case_management=False, disable_autosave_load=True)
    else:
        panel = panel_cls()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)
    return panel


def _activate_q_increase_mode(panel, q_increased_text):
    panel.inc_cb.setChecked(True)
    panel.inc_mode_q_rb.setChecked(True)
    panel.inc_q_edit.setText(q_increased_text)
    _flush_events(3)


def _assert_single_visible_increase_input(panel, *, percent_visible):
    assert panel.inc_mode_percent_rb.isChecked() is percent_visible
    assert panel.inc_mode_q_rb.isChecked() is (not percent_visible)
    assert panel.inc_lbl.isVisible() is percent_visible
    assert panel.inc_edit.isVisible() is percent_visible
    assert panel.inc_q_lbl.isVisible() is (not percent_visible)
    assert panel.inc_q_edit.isVisible() is (not percent_visible)


@pytest.mark.parametrize(
    ("folder", "class_name"),
    [
        ("open_channel", "OpenChannelPanel"),
        ("aqueduct", "AqueductPanel"),
        ("tunnel", "TunnelPanel"),
        ("culvert", "CulvertPanel"),
        ("pressure_pipe", "PressurePipePanel"),
    ],
)
def test_panels_only_show_default_percent_increase_input_on_first_open(
    folder, class_name
):
    panel = _new_panel(folder, class_name)

    _assert_single_visible_increase_input(panel, percent_visible=True)

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_open_channel_panel_q_increase_mode_roundtrips_and_drives_manual_percent():
    panel = _new_panel("open_channel", "OpenChannelPanel")

    panel.Q_edit.setText("5.0")
    _activate_q_increase_mode(panel, "5.5")

    panel._save_current_case()
    saved_case = dict(panel._cases[panel._current_case_idx])

    assert saved_case["inc_mode"] == "q_increased"
    assert saved_case["inc_q_text"] == "5.5"

    panel.inc_mode_percent_rb.setChecked(True)
    panel.inc_edit.setText("20")
    panel.inc_q_edit.setText("")
    panel._load_case(panel._current_case_idx)
    _flush_events(2)

    assert panel.inc_mode_q_rb.isChecked() is True
    assert panel.inc_q_edit.text() == "5.5"
    assert panel.inc_derived_hint.text() == "系统换算：流量加大比例 = 10.000%"

    params, result = panel._parse_and_calc_case(saved_case, 1)

    assert params["manual_increase"] == pytest.approx(10.0)
    assert result["increase_percent"] == pytest.approx(10.0)
    assert result["Q_increased"] == pytest.approx(5.5)

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_aqueduct_panel_q_increase_mode_roundtrips_and_drives_manual_percent():
    panel = _new_panel("aqueduct", "AqueductPanel")

    panel.Q_edit.setText("5.0")
    _activate_q_increase_mode(panel, "5.5")

    panel._save_current_case()
    saved_case = dict(panel._cases[panel._current_case_idx])

    assert saved_case["inc_mode"] == "q_increased"
    assert saved_case["inc_q_text"] == "5.5"

    panel.inc_mode_percent_rb.setChecked(True)
    panel.inc_edit.setText("20")
    panel.inc_q_edit.setText("")
    panel._load_case(panel._current_case_idx)
    _flush_events(2)

    assert panel.inc_mode_q_rb.isChecked() is True
    assert panel.inc_q_edit.text() == "5.5"
    assert panel.inc_derived_hint.text() == "系统换算：流量加大比例 = 10.000%"

    params, result = panel._parse_and_calc_case(saved_case, 1)

    assert params["manual_increase"] == pytest.approx(10.0)
    assert result["increase_percent"] == pytest.approx(10.0)
    assert result["Q_increased"] == pytest.approx(5.5)

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_tunnel_panel_q_increase_mode_roundtrips_and_drives_manual_percent():
    panel = _new_panel("tunnel", "TunnelPanel")

    panel.Q_edit.setText("5.0")
    _activate_q_increase_mode(panel, "5.5")

    panel._save_current_case()
    saved_case = dict(panel._cases[panel._current_case_idx])

    assert saved_case["inc_mode"] == "q_increased"
    assert saved_case["inc_q_text"] == "5.5"

    panel.inc_mode_percent_rb.setChecked(True)
    panel.inc_edit.setText("20")
    panel.inc_q_edit.setText("")
    panel._load_case(panel._current_case_idx)
    _flush_events(2)

    assert panel.inc_mode_q_rb.isChecked() is True
    assert panel.inc_q_edit.text() == "5.5"
    assert panel.inc_derived_hint.text() == "系统换算：流量加大比例 = 10.000%"

    params, result = panel._parse_and_calc_case(saved_case, 1)

    assert params["manual_increase"] == pytest.approx(10.0)
    assert result["increase_percent"] == pytest.approx(10.0)
    assert result["Q_increased"] == pytest.approx(5.5)

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_culvert_panel_q_increase_mode_roundtrips_and_drives_manual_percent():
    panel = _new_panel("culvert", "CulvertPanel")

    panel.Q_edit.setText("5.0")
    _activate_q_increase_mode(panel, "5.5")

    panel._save_current_case()
    saved_case = dict(panel._cases[panel._current_case_idx])

    assert saved_case["inc_mode"] == "q_increased"
    assert saved_case["inc_q_text"] == "5.5"

    panel.inc_mode_percent_rb.setChecked(True)
    panel.inc_edit.setText("20")
    panel.inc_q_edit.setText("")
    panel._load_case(panel._current_case_idx)
    _flush_events(2)

    assert panel.inc_mode_q_rb.isChecked() is True
    assert panel.inc_q_edit.text() == "5.5"
    assert panel.inc_derived_hint.text() == "系统换算：流量加大比例 = 10.000%"

    params = panel._parse_case(saved_case, 1)

    assert params["manual_increase"] == pytest.approx(10.0)

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_pressure_pipe_panel_q_increase_mode_roundtrips_and_drives_manual_percent():
    panel = _new_panel("pressure_pipe", "PressurePipePanel")

    panel.Q_edit.setText("0.5")
    _activate_q_increase_mode(panel, "0.55")

    panel._save_current_case()
    saved_case = dict(panel._cases[panel._current_case_idx])

    assert saved_case["inc_mode"] == "q_increased"
    assert saved_case["inc_q_text"] == "0.55"

    panel.inc_mode_percent_rb.setChecked(True)
    panel.inc_edit.setText("30")
    panel.inc_q_edit.setText("")
    panel._load_case(panel._current_case_idx)
    _flush_events(2)

    assert panel.inc_mode_q_rb.isChecked() is True
    assert panel.inc_q_edit.text() == "0.55"
    assert panel.inc_derived_hint.text() == "系统换算：流量加大比例 = 10.000%"

    parsed = panel._parse_case(saved_case, 1)

    assert parsed.manual_increase_percent == pytest.approx(10.0)

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_pressure_pipe_project_roundtrip_restores_success_result_and_export_text():
    panel = _new_panel("pressure_pipe", "PressurePipePanel")

    panel.Q_edit.setText("0.5")
    panel.length_edit.setText("1000")
    panel.local_ratio_edit.setText("0.15")
    panel.inc_cb.setChecked(True)
    panel.inc_edit.setText("")
    panel._calculate()
    _flush_events(8)

    assert panel._all_results
    assert panel.current_result is not None
    assert panel._export_plain_text.strip()

    saved = panel.to_project_dict()
    restored = _new_panel("pressure_pipe", "PressurePipePanel")
    restored.from_project_dict(saved)
    _flush_events(8)

    assert len(restored._all_results) == len(panel._all_results)
    assert restored.current_result is not None
    assert restored.current_result.recommended is not None
    assert restored._export_plain_text == panel._export_plain_text
    assert restored._has_rendered_results is True

    panel.close()
    panel.deleteLater()
    restored.close()
    restored.deleteLater()
    _flush_events(4)


def test_pressure_pipe_project_roundtrip_restores_input_error_result_card():
    panel = _new_panel("pressure_pipe", "PressurePipePanel")

    panel.Q_edit.setText("")
    panel._calculate()
    _flush_events(8)

    assert panel._all_results
    assert panel.current_result is not None
    assert panel.current_result.recommended is None
    assert "请输入设计流量 Q" in panel.current_result.reason

    saved = panel.to_project_dict()
    restored = _new_panel("pressure_pipe", "PressurePipePanel")
    restored.from_project_dict(saved)
    _flush_events(8)

    assert len(restored._all_results) == 1
    assert restored.current_result is not None
    assert restored.current_result.recommended is None
    assert "请输入设计流量 Q" in restored.current_result.reason
    assert "请输入设计流量 Q" in restored._export_plain_text

    panel.close()
    panel.deleteLater()
    restored.close()
    restored.deleteLater()
    _flush_events(4)


def test_siphon_panel_q_increase_mode_roundtrips_in_project_payload():
    panel = _new_panel("siphon", "SiphonPanel")

    panel.edit_Q.setText("1.0")
    _activate_q_increase_mode(panel, "1.1")

    payload = panel.to_dict()

    assert payload["inc_mode"] == "q_increased"
    assert payload["inc_q_text"] == "1.1"

    restored = _new_panel("siphon", "SiphonPanel")
    restored.from_dict(payload)
    _flush_events(2)

    assert restored.inc_mode_q_rb.isChecked() is True
    assert restored.inc_q_edit.text() == "1.1"
    assert restored.inc_derived_hint.text() == "系统换算：流量加大比例 = 10.000%"

    panel.close()
    panel.deleteLater()
    restored.close()
    restored.deleteLater()
    _flush_events(4)


def test_siphon_panel_uses_left_narrow_right_wide_flow_bar():
    panel = _new_panel("siphon", "SiphonPanel")

    assert panel.flow_bar_left.width() < panel.flow_bar_right.width()
    assert panel.flow_bar_right.width() > panel.flow_bar_left.width() * 1.5
    assert panel.inc_cb.width() >= panel.inc_cb.sizeHint().width()

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_siphon_panel_shows_compact_hint_and_full_help_tooltip():
    panel = _new_panel("siphon", "SiphonPanel")

    assert panel.lbl_inc_compact_hint.isVisible() is True
    assert panel.lbl_inc_compact_hint.text() == "留空按规范取值"
    assert "按比例" in panel.btn_inc_help.toolTip()
    assert "按Q加大" in panel.btn_inc_help.toolTip()
    assert "设计流量 Q" in panel.btn_inc_help.toolTip()
    assert _find_tooltip_filter(panel.btn_inc_help)._tooltipDelay == 200
    assert "工程实际管径已由工程师自行确定" in panel.btn_D_help.toolTip()
    assert "覆盖自动计算结果" in panel.btn_D_help.toolTip()
    assert "R=nD" in panel.btn_D_help.toolTip()
    assert _find_tooltip_filter(panel.btn_D_help)._tooltipDelay == 200
    panel.btn_D_help.click()
    _flush_events(2)
    assert hasattr(panel, "lbl_D_help") is False

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_siphon_panel_switching_modes_only_shows_matching_input():
    panel = _new_panel("siphon", "SiphonPanel")

    assert panel.lbl_inc_percent.isVisible() is True
    assert panel.edit_inc.isVisible() is True
    assert panel.lbl_inc_q.isVisible() is False
    assert panel.inc_q_edit.isVisible() is False

    panel.inc_mode_q_rb.setChecked(True)
    _flush_events(3)

    assert panel.lbl_inc_percent.isVisible() is False
    assert panel.edit_inc.isVisible() is False
    assert panel.lbl_inc_q.isVisible() is True
    assert panel.inc_q_edit.isVisible() is True

    panel.inc_mode_percent_rb.setChecked(True)
    _flush_events(3)

    assert panel.lbl_inc_percent.isVisible() is True
    assert panel.edit_inc.isVisible() is True
    assert panel.lbl_inc_q.isVisible() is False
    assert panel.inc_q_edit.isVisible() is False

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_siphon_panel_places_threshold_between_velocity_and_turn_radius_columns():
    panel = _new_panel("siphon", "SiphonPanel")

    velocity_pos = panel.edit_v.mapTo(panel, QPoint(0, 0))
    threshold_pos = panel.edit_threshold.mapTo(panel, QPoint(0, 0))
    turn_n_pos = panel.edit_turn_n.mapTo(panel, QPoint(0, 0))

    assert threshold_pos.x() > velocity_pos.x() + panel.edit_v.width()
    assert threshold_pos.x() + panel.edit_threshold.width() < turn_n_pos.x()
    assert abs(threshold_pos.y() - velocity_pos.y()) <= 20

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_open_channel_detail_output_uses_high_precision_increase_formula_text():
    panel = _new_panel("open_channel", "OpenChannelPanel")

    panel.Q_edit.setText("5.0")
    _activate_q_increase_mode(panel, "5.91")
    panel._save_current_case()
    saved_case = dict(panel._cases[panel._current_case_idx])

    params, result = panel._parse_and_calc_case(saved_case, 1)
    panel.input_params = params
    panel._show_trapezoid_detail(result)

    assert "流量加大比例 = 18.200%" in panel._export_plain_text
    assert "Q加大 = Q × (1 + 0.18200)" in panel._export_plain_text
    assert "= 5.000 × 1.18200" in panel._export_plain_text

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_aqueduct_detail_output_uses_high_precision_increase_formula_text():
    panel = _new_panel("aqueduct", "AqueductPanel")

    panel.Q_edit.setText("5.0")
    _activate_q_increase_mode(panel, "5.91")
    panel._save_current_case()
    saved_case = dict(panel._cases[panel._current_case_idx])

    params, result = panel._parse_and_calc_case(saved_case, 1)
    panel.input_params = params
    panel._show_u_detail(result)

    assert "流量加大比例 = 18.200%" in panel._export_plain_text
    assert "Q加大 = Q × (1 + 0.18200)" in panel._export_plain_text
    assert "= 5.000 × 1.18200" in panel._export_plain_text

    panel.close()
    panel.deleteLater()
    _flush_events(4)
