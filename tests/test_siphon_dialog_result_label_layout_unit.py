# -*- coding: utf-8 -*-
"""
倒虹吸结果标签布局回归测试。
验证拦污栅与进口断面弹窗里的单行结果标签不会被压扁，也不会随窗口拉高而异常变高。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.dialogs as siphon_dialogs_mod


class _FakeWebView(QWidget):
    """测试替身：避免 QWebEngineView 在无头环境下启动子进程。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.html = ""

    def setHtml(self, html, *_args, **_kwargs):
        """记录最近一次 HTML，兼容真实控件调用方式。"""
        self.html = html


def _fake_web_view_factory(parent=None):
    """返回轻量测试 WebView。"""
    return _FakeWebView(parent)


def _get_qapp():
    """获取测试可复用的 QApplication。"""
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 6):
    """刷新事件循环，等待布局稳定。"""
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def test_trash_rack_result_label_uses_xis_prefix_and_keeps_stable_height(monkeypatch):
    """拦污栅结果标签应显示 ξs，且窗口拉高后高度保持稳定。"""
    _get_qapp()
    monkeypatch.setattr(siphon_dialogs_mod, "create_web_view", _fake_web_view_factory)

    dialog = siphon_dialogs_mod.TrashRackConfigDialog(
        None,
        siphon_dialogs_mod.TrashRackParams(),
    )
    dialog.show()
    _flush_events()

    label = dialog.lbl_result
    initial_height = label.height()
    font_height = label.fontMetrics().height()

    assert label.text().startswith("ξs = ")
    assert initial_height >= font_height + 12

    dialog.resize(dialog.width(), dialog.height() + 240)
    _flush_events()

    assert label.height() == initial_height

    dialog.close()
    dialog.deleteLater()


def test_inlet_section_result_label_keeps_stable_height_when_window_resizes():
    """进口断面结果标签应留出足够高度，且不随窗口拉高而异常变高。"""
    _get_qapp()

    dialog = siphon_dialogs_mod.InletSectionDialog(None, Q=10.0)
    dialog.show()
    _flush_events()

    label = dialog.lbl_result
    initial_height = label.height()
    font_height = label.fontMetrics().height()

    assert initial_height >= font_height + 10

    dialog.resize(dialog.width(), dialog.height() + 240)
    _flush_events()

    assert label.height() == initial_height

    dialog.close()
    dialog.deleteLater()
