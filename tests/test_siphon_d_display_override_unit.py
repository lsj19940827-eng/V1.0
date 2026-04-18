# -*- coding: utf-8 -*-
"""倒虹吸 D 显示与指定管径模式回归测试。"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "倒虹吸水力计算系统"))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod


_NO_WRAP_MARKER = "\u2060"


class _FakeWebEngineView(QWidget):
    """避免测试环境触发真实的 WebEngine 依赖。"""

    def setHtml(self, *_args, **_kwargs):
        return None


class _FakeCaseManager:
    """用最小工况管理器模拟工况切换。"""

    def __init__(self, payloads):
        self._payloads = payloads

    def load_case_data(self, case):
        return dict(self._payloads[case.name])


def _get_qapp():
    """获取或创建 QApplication。"""
    return QApplication.instance() or QApplication(sys.argv)


def _build_panel(monkeypatch):
    """创建一个关闭 autosave 的倒虹吸面板。"""
    _get_qapp()
    monkeypatch.setattr(
        siphon_panel_mod,
        "create_web_view",
        lambda parent=None: _FakeWebEngineView(parent),
    )
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    panel.inc_cb.setChecked(False)
    return panel


def _flush_ui(delay_ms=0):
    """冲刷事件循环，必要时等待防抖计时器。"""
    app = _get_qapp()
    app.processEvents()
    if delay_ms > 0:
        QTest.qWait(delay_ms)
        app.processEvents()


def _visible_label_text(label):
    """返回去掉防换行标记后的可见文本。"""
    return label.text().replace(_NO_WRAP_MARKER, "")


def _second_line_required_width(label):
    """返回标签第二行文字的理论所需宽度。"""
    lines = label.text().split("\n")
    assert len(lines) >= 2
    return label.fontMetrics().horizontalAdvance(lines[1])


def _snapshot_pipe_widths(panel):
    """采集参数区三列和面板建议宽度。"""
    params_layout = panel._pipe_base_column.parentWidget().layout()
    return {
        "panel_width": panel.width(),
        "minimum_hint_width": panel.minimumSizeHint().width(),
        "pipe_column_width": panel._pipe_base_column.width(),
        "pipe_column_minimum_width": panel._pipe_base_column.minimumWidth(),
        "middle_column_width": params_layout.itemAt(2).widget().width(),
        "right_column_width": params_layout.itemAt(4).widget().width(),
        "label_width": panel.lbl_D_theory.width(),
    }


def test_default_panel_immediately_shows_realtime_d_value(monkeypatch):
    """首次打开面板时，D 应立即显示实时设计值与理论值。"""
    panel = _build_panel(monkeypatch)

    _flush_ui()

    assert panel.lbl_D_theory.text() == "D设计 = 2.6000 m\n（D理论 = 2.5231 m）"
    assert panel.lbl_D_theory.wordWrap() is True

    panel.deleteLater()


def test_multi_pipe_d_label_includes_theory_design_and_single_pipe_flow(monkeypatch):
    """多管并联时，D 标签应同时显示理论值、设计值和每管流量。"""
    panel = _build_panel(monkeypatch)

    panel.spin_num_pipes.setValue(2)
    _flush_ui(delay_ms=250)

    text = _visible_label_text(panel.lbl_D_theory)
    assert "D设计 = 1.8000 m" in text
    assert "D理论 = 1.7841 m" in text
    assert "每管Q = 5.000 m³/s" in text

    panel.deleteLater()


def test_multi_pipe_unconfirmed_d_label_protects_m3s_from_wrapping(monkeypatch):
    """多管未确认时，m³/s 单位应带防换行标记。"""
    panel = _build_panel(monkeypatch)

    panel.spin_num_pipes.setValue(2)
    _flush_ui(delay_ms=250)

    assert panel._num_pipes_user_confirmed is False
    assert f"m³{_NO_WRAP_MARKER}/{_NO_WRAP_MARKER}s" in panel.lbl_D_theory.text()
    assert "每管Q = 5.000 m³/s" in _visible_label_text(panel.lbl_D_theory)

    panel.deleteLater()


def test_multi_pipe_d_label_keeps_second_line_width_in_near_threshold_window(monkeypatch):
    """窄窗口下左栏也应保住 D 第二行的完整显示宽度。"""
    panel = _build_panel(monkeypatch)
    panel.resize(1400, 520)
    panel.show()
    _flush_ui(delay_ms=200)

    panel.spin_num_pipes.setValue(2)
    _flush_ui(delay_ms=250)

    required_width = _second_line_required_width(panel.lbl_D_theory)
    assert panel.lbl_D_theory.width() >= required_width
    assert hasattr(panel, "_pipe_base_column")

    panel._num_pipes_user_confirmed = True
    panel._update_num_pipes_style()
    _flush_ui(delay_ms=100)

    assert panel.lbl_D_theory.width() >= required_width

    panel.close()
    panel.deleteLater()


def test_pipe_base_width_stays_stable_when_num_pipes_toggles(monkeypatch):
    """N 在 1 和 2 之间切换时，参数区宽度不应再跟着抖动。"""
    panel = _build_panel(monkeypatch)
    panel.resize(1400, 520)
    panel.show()
    _flush_ui(delay_ms=200)

    panel.spin_num_pipes.setValue(1)
    _flush_ui(delay_ms=250)
    first_single = _snapshot_pipe_widths(panel)

    panel.spin_num_pipes.setValue(2)
    _flush_ui(delay_ms=250)
    dual_pipe = _snapshot_pipe_widths(panel)

    panel.spin_num_pipes.setValue(1)
    _flush_ui(delay_ms=250)
    second_single = _snapshot_pipe_widths(panel)

    assert first_single["minimum_hint_width"] == dual_pipe["minimum_hint_width"] == second_single["minimum_hint_width"]
    assert first_single["middle_column_width"] == dual_pipe["middle_column_width"] == second_single["middle_column_width"]

    panel.close()
    panel.deleteLater()


def test_pipe_base_width_stays_stable_when_override_toggles_in_multi_pipe_mode(monkeypatch):
    """多管场景切换指定管径时，参数区宽度不应继续变宽。"""
    panel = _build_panel(monkeypatch)
    panel.resize(1400, 520)
    panel.show()
    _flush_ui(delay_ms=200)

    panel.spin_num_pipes.setValue(2)
    _flush_ui(delay_ms=250)
    normal_multi = _snapshot_pipe_widths(panel)

    panel.cb_D_override.setChecked(True)
    _flush_ui(delay_ms=50)
    panel.edit_D_override.setText("1.2")
    _flush_ui(delay_ms=250)
    override_multi = _snapshot_pipe_widths(panel)

    panel.cb_D_override.setChecked(False)
    _flush_ui(delay_ms=250)
    restored_multi = _snapshot_pipe_widths(panel)

    assert normal_multi["minimum_hint_width"] == override_multi["minimum_hint_width"] == restored_multi["minimum_hint_width"]
    assert normal_multi["middle_column_width"] == override_multi["middle_column_width"] == restored_multi["middle_column_width"]

    panel.close()
    panel.deleteLater()


def test_case_switch_isolates_confirmation_state_by_case(monkeypatch):
    """切换工况时，确认状态应按工况隔离，不得串工况。"""
    panel = _build_panel(monkeypatch)
    panel.case_manager = _FakeCaseManager(
        {
            "工况1": {"Q": 10.0, "v_guess": 2.0, "n": 0.014, "num_pipes": 1},
            "工况2": {"Q": 10.0, "v_guess": 2.0, "n": 0.014, "num_pipes": 1},
        }
    )
    case1 = SimpleNamespace(name="工况1")
    case2 = SimpleNamespace(name="工况2")

    panel._on_case_selected(case1)
    _flush_ui()
    assert panel._v_user_confirmed is False
    assert panel._num_pipes_user_confirmed is False
    assert panel._turn_n_user_confirmed is False

    panel._v_user_confirmed = True
    panel._num_pipes_user_confirmed = True
    panel._turn_n_user_confirmed = True

    panel._on_case_selected(case2)
    _flush_ui()
    assert panel._v_user_confirmed is False
    assert panel._num_pipes_user_confirmed is False
    assert panel._turn_n_user_confirmed is False
    assert panel.lbl_D_theory.text().startswith("D设计 = ")

    panel._on_case_selected(case1)
    _flush_ui()
    assert panel._v_user_confirmed is True
    assert panel._num_pipes_user_confirmed is True
    assert panel._turn_n_user_confirmed is True

    panel.deleteLater()


def test_d_override_mode_uses_actual_velocity_and_restores_previous_value(monkeypatch):
    """指定管径生效后应切到实际流速，并在取消时恢复原拟定流速。"""
    panel = _build_panel(monkeypatch)

    panel.edit_v.setText("2.2")
    panel._v_user_confirmed = True
    panel._update_v_style()

    panel.cb_D_override.setChecked(True)
    _flush_ui()
    assert panel.edit_v.isReadOnly() is False

    panel.edit_D_override.setText("3.0")
    _flush_ui(delay_ms=250)

    assert panel.edit_v.isReadOnly() is True
    assert float(panel.edit_v.text()) == pytest.approx(1.4147, abs=1e-4)
    assert panel.lbl_D_theory.text() == "采用D = 3.0000 m\n（实际流速 = 1.4147 m/s）"

    panel._v_user_confirmed = False
    assert panel._validate_v_before_calc() is True

    panel.cb_D_override.setChecked(False)
    _flush_ui()

    assert panel.edit_v.isReadOnly() is False
    assert float(panel.edit_v.text()) == pytest.approx(2.2, abs=1e-6)
    assert panel._v_user_confirmed is True

    panel.deleteLater()


def test_d_override_backup_roundtrip_restores_velocity_after_reload(monkeypatch):
    """指定管径模式保存并恢复后，取消指定仍应找回原拟定流速。"""
    panel = _build_panel(monkeypatch)
    panel.edit_v.setText("2.2")
    panel._v_user_confirmed = True
    panel._update_v_style()
    panel.cb_D_override.setChecked(True)
    panel.edit_D_override.setText("3.0")
    _flush_ui(delay_ms=250)

    payload = panel.to_dict()
    assert payload["v_before_override"] == 2.2
    assert payload["v_confirmed_before_override"] is True

    restored = _build_panel(monkeypatch)
    restored.from_dict(payload)
    _flush_ui()

    assert restored.cb_D_override.isChecked() is True
    assert restored.edit_v.isReadOnly() is True
    assert float(restored.edit_v.text()) == pytest.approx(1.4147, abs=1e-4)

    restored.cb_D_override.setChecked(False)
    _flush_ui()

    assert float(restored.edit_v.text()) == pytest.approx(2.2, abs=1e-6)
    assert restored._v_user_confirmed is True

    panel.deleteLater()
    restored.deleteLater()
