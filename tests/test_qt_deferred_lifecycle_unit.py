"""真实控件销毁后，延迟任务不得继续访问已释放的 Qt 对象。"""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('CODEX_FORCE_QTEXTBROWSER', '1')

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


@pytest.fixture(scope='module')
def app():
    value = QApplication.instance() or QApplication([])
    yield value
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    value.processEvents()


def delete_widget(widget):
    """明确先完成 C++ 销毁，再推进尚未到期的回调，复现关闭时序。"""
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(widget, QEvent.DeferredDelete)
    assert not isValid(widget)


@pytest.mark.parametrize('deleted', [False, True])
def test_multi_siphon_warning_timer_follows_dialog_lifetime(app, monkeypatch, deleted):
    from app_渠系计算前端.siphon import multi_siphon_dialog as module
    from 推求水面线.utils.siphon_extractor import SiphonGroup

    calls = []
    warnings = []
    original = module.MultiSiphonDialog._show_velocity_source_warnings_once

    def record_warning(self):
        calls.append(isValid(self))
        # 失效调用已经足以复现问题；不把无效 parent 送入原生 InfoBar 造成进程崩溃。
        if isValid(self):
            original(self)

    monkeypatch.setattr(module.MultiSiphonDialog, '_show_velocity_source_warnings_once', record_warning)
    monkeypatch.setattr(module.InfoBar, 'warning', lambda *a, **kw: warnings.append(isValid(kw['parent'])))
    dialog = module.MultiSiphonDialog(None, [SiphonGroup(name='生命周期测试')])
    if deleted:
        delete_widget(dialog)
    QTest.qWait(120)
    if not deleted:
        delete_widget(dialog)
    assert calls == ([] if deleted else [True])
    assert warnings == ([] if deleted else [True])


@pytest.mark.parametrize('deleted', [False, True])
def test_water_profile_layout_callbacks_follow_panel_lifetime(app, monkeypatch, deleted):
    from app_渠系计算前端.water_profile.panel import WaterProfilePanel

    calls = []
    original = WaterProfilePanel._adjust_splitter_for_settings

    def record_adjust(self):
        calls.append(isValid(self))
        if isValid(self):
            original(self)

    monkeypatch.setattr(WaterProfilePanel, '_adjust_splitter_for_settings', record_adjust)
    panel = WaterProfilePanel()
    panel._schedule_adjust_splitter_for_settings()
    if deleted:
        delete_widget(panel)
    QTest.qWait(130)
    if not deleted:
        delete_widget(panel)
    assert calls == ([] if deleted else [True, True])


@pytest.mark.parametrize('load_from_manager', [False, True])
@pytest.mark.parametrize('deleted', [False, True])
def test_siphon_startup_load_follows_panel_lifetime(app, monkeypatch, load_from_manager, deleted):
    from app_渠系计算前端.siphon.panel import SiphonPanel

    calls = []
    method = '_load_from_manager' if load_from_manager else '_load_autosave'
    monkeypatch.setattr(SiphonPanel, method, lambda self: calls.append(isValid(self)))
    panel = SiphonPanel(show_case_management=False, siphon_manager=object() if load_from_manager else None)
    if deleted:
        delete_widget(panel)
    QTest.qWait(140)
    if not deleted:
        delete_widget(panel)
    assert calls == ([] if deleted else [True])


def test_siphon_autosave_timer_is_destroyed_with_panel(app, monkeypatch, tmp_path):
    from app_渠系计算前端.siphon import panel as module

    calls = []
    # 工况创建与保存只访问本用例独立目录。
    monkeypatch.setattr(module, '_pkg_root', str(tmp_path))
    monkeypatch.setattr(module.SiphonPanel, '_do_autosave', lambda self: calls.append(isValid(self)))
    panel = module.SiphonPanel(show_case_management=True, disable_autosave_load=True)
    timer = panel._autosave_timer
    timer.start(50)
    delete_widget(panel)
    QTest.qWait(110)
    assert not isValid(timer)
    assert calls == []


@pytest.mark.parametrize('deleted', [False, True])
def test_multi_siphon_raise_timer_follows_dialog_lifetime(app, monkeypatch, deleted):
    from app_渠系计算前端.siphon.multi_siphon_dialog import MultiSiphonDialog

    calls = []
    monkeypatch.setattr(MultiSiphonDialog, '_ensure_visible', lambda self: calls.append(isValid(self)))
    dialog = MultiSiphonDialog(None, [])
    dialog.show()
    if deleted:
        delete_widget(dialog)
    QTest.qWait(100)
    if not deleted:
        delete_widget(dialog)
    assert calls == ([] if deleted else [True])


def test_live_siphon_autosave_still_persists_current_inputs(app, monkeypatch, tmp_path):
    from app_渠系计算前端.siphon import panel as module

    monkeypatch.setattr(module, '_pkg_root', str(tmp_path))
    panel = module.SiphonPanel(show_case_management=True, disable_autosave_load=True)
    try:
        panel.edit_Q.setText('1.234')
        panel._mark_dirty()
        panel._autosave_timer.start(30)
        QTest.qWait(100)
        assert not panel._data_dirty
        case = panel._get_current_case()
        assert panel.case_manager.load_case_data(case)['Q'] == pytest.approx(1.234)
    finally:
        delete_widget(panel)
