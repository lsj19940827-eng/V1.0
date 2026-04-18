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

    text = panel.lbl_D_theory.text()
    assert "D设计 = 1.8000 m" in text
    assert "D理论 = 1.7841 m" in text
    assert "每管Q = 5.000 m³/s" in text

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
