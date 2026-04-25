# -*- coding: utf-8 -*-
"""倒虹吸面板默认值与 set_params 自动填入（GUI）单元测试。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod


class _FakeWebEngineView(QWidget):
    """测试替身：避免 QWebEngineView 在无头环境触发子进程崩溃。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _fake_web_view_factory(parent=None):
    return _FakeWebEngineView(parent)


def _get_qapp():
    return QApplication.instance() or QApplication([])


def test_set_params_autofills_increased_velocity_fields(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel.set_params(v_channel_in_inc=1.23456, v_pipe_out_inc=2.34567)

    assert panel.edit_v1_inc.text() == "1.2346"
    assert panel.edit_v3_inc.text() == "2.3457"
    assert "已导入" in panel.lbl_v1_inc.text()
    assert "已导入" in panel.lbl_v3_inc.text()

    panel.deleteLater()


def test_panel_defaults_to_linear_twist_transition(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)

    assert panel.combo_inlet_type.currentText() == "直线扭曲面"
    assert panel.combo_outlet_type.currentText() == "直线扭曲面"
    assert panel.edit_xi_inlet.text() == "0.2000"
    assert panel.edit_xi_outlet.text() == "0.4000"

    panel.deleteLater()


def test_from_dict_preserves_explicit_none_transition_values(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel.from_dict(
        {
            "inlet_type": "无",
            "outlet_type": "无",
            "xi_inlet": 0.0,
            "xi_outlet": 0.0,
        }
    )

    assert panel.combo_inlet_type.currentText() == "无"
    assert panel.combo_outlet_type.currentText() == "无"
    assert panel.edit_xi_inlet.text() == "0.0"
    assert panel.edit_xi_outlet.text() == "0.0"

    panel.deleteLater()


def test_from_dict_does_not_print_debug_by_default(monkeypatch, capsys):
    """默认未开启调试开关时，恢复倒虹吸数据不应污染终端输出。"""
    _get_qapp()
    monkeypatch.delenv("APP_DEBUG", raising=False)
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    capsys.readouterr()

    panel.from_dict({"Q": 1.0, "v_guess": 2.0, "calculated_at": "2026-04-25 10:00:00"})

    captured = capsys.readouterr()
    assert "[DEBUG SiphonPanel.from_dict]" not in captured.out

    panel.deleteLater()

