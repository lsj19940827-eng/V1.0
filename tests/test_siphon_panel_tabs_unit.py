# -*- coding: utf-8 -*-
"""倒虹吸页签与结构段入口单元测试。"""

import os

from PySide6.QtWidgets import QApplication, QWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

import app_渠系计算前端.siphon.panel as siphon_panel_mod


class _FakeWebEngineView(QWidget):
    """测试替身：避免无头环境下 QWebEngineView 崩溃。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _fake_web_view_factory(parent=None):
    """返回假的网页视图。"""
    return _FakeWebEngineView(parent)


def _get_qapp():
    """获取或创建 QApplication。"""
    return QApplication.instance() or QApplication([])


def _find_text_widgets(parent, text):
    """递归查找带指定文字的子控件。"""
    matches = []
    for child in parent.findChildren(QWidget):
        getter = getattr(child, "text", None)
        if callable(getter):
            try:
                if getter() == text:
                    matches.append(child)
            except TypeError:
                continue
    return matches


def test_top_tabs_hide_longitudinal_nodes_but_keep_edit_entry(monkeypatch):
    """顶部不再显示纵断面节点页签，但结构段页应保留编辑入口。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)

    tab_texts = [
        panel.params_notebook.tabText(index)
        for index in range(panel.params_notebook.count())
    ]
    structure_tab = panel.params_notebook.widget(1)

    assert "纵断面节点" not in tab_texts
    assert _find_text_widgets(structure_tab, "编辑纵断面节点")

    panel.deleteLater()
