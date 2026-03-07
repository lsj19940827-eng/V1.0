# -*- coding: utf-8 -*-
"""倒虹吸面板 set_params 自动填入（GUI）单元测试。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod


class _FakeWebEngineView(QWidget):
    """测试替身：避免 QWebEngineView 在无头环境触发子进程崩溃。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _get_qapp():
    return QApplication.instance() or QApplication([])


def test_set_params_autofills_increased_velocity_fields(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "QWebEngineView", _FakeWebEngineView)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel.set_params(v_channel_in_inc=1.23456, v_pipe_out_inc=2.34567)

    assert panel.edit_v1_inc.text() == "1.2346"
    assert panel.edit_v3_inc.text() == "2.3457"
    assert "已导入" in panel.lbl_v1_inc.text()
    assert "已导入" in panel.lbl_v3_inc.text()

    panel.deleteLater()

