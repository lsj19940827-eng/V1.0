"""工程恢复事务与后台自动保存的跨阶段行为。"""

import copy
import json
import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app_渠系计算前端 import project_manager as module
from app_渠系计算前端 import report_meta
from 推求水面线.managers.siphon_manager import SiphonManager


@pytest.fixture
def runtime(monkeypatch):
    app = QApplication.instance() or QApplication([])
    state = [report_meta.ReportMeta(project_name='原工程')]
    monkeypatch.setattr(report_meta, 'load_meta', lambda: copy.deepcopy(state[0]))
    monkeypatch.setattr(report_meta, 'save_meta', lambda value: state.__setitem__(0, copy.deepcopy(value)))
    manager = module.ProjectManager()
    monkeypatch.setattr(manager, '_check_save_before_close', lambda: True)
    monkeypatch.setattr(manager, '_add_recent_project', lambda path: None)
    monkeypatch.setattr(module.QMessageBox, 'critical', lambda *args: None)
    yield app, manager, state
    assert manager.finish_background_save(5000)
    manager.deleteLater()
    app.processEvents()


def test_future_version_does_not_change_session_or_report_settings(runtime, tmp_path):
    _app, manager, meta = runtime
    manager._current_path = '原工程.qxproj'
    manager.mark_dirty()
    path = tmp_path / '未来工程.qxproj'
    path.write_text(json.dumps({'version': '99.0', 'report_meta': {'project_name': '新工程'}}), encoding='utf-8')
    assert not manager.open_project(str(path))
    assert manager.current_path == '原工程.qxproj'
    assert manager.is_dirty
    assert meta[0].project_name == '原工程'


def test_invalid_table_snapshot_is_rejected_before_any_restore(runtime, tmp_path, monkeypatch):
    _app, manager, _meta = runtime
    called = []
    monkeypatch.setattr(manager, '_restore_project_data', lambda data: called.append(data))
    path = tmp_path / '坏表格工程.qxproj'
    path.write_text(json.dumps({'water_profile_panel': {'table_state': []}}), encoding='utf-8')
    assert not manager.open_project(str(path))
    assert called == []


def test_bad_legacy_sidecar_does_not_change_runtime(runtime, tmp_path, monkeypatch):
    _app, manager, meta = runtime
    restored = []
    monkeypatch.setattr(manager, '_restore_project_data', restored.append)
    path = tmp_path / '旧工程.qxproj'
    path.write_text('{}', encoding='utf-8')
    path.with_suffix('.siphon.json').write_text('{损坏', encoding='utf-8')
    assert not manager.open_project(str(path))
    assert restored == []
    assert manager.session.generation == 0
    assert meta[0].project_name == '原工程'


def test_save_as_binds_path_without_loading_existing_stale_sidecar(runtime, tmp_path, monkeypatch):
    _app, manager, _meta = runtime
    service = SiphonManager(load_existing=False)
    service.from_dict({'siphons': {'当前数据': {'Q': 1.25}}})
    manager._siphon_manager = service
    path = tmp_path / '另存为.qxproj'
    sidecar = path.with_suffix('.siphon.json')
    sidecar.write_text(json.dumps({'siphons': {'旧旁文件': {}}}), encoding='utf-8')
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *args: (str(path), ''))
    manager.mark_dirty()
    assert manager.save_as_project()
    assert service.to_dict()['siphons'] == {'当前数据': {'Q': 1.25}}
    assert service.config_path == str(sidecar)
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved['siphon_manager_data']['siphons'] == {'当前数据': {'Q': 1.25}}
    assert not manager.is_dirty


def test_unknown_top_level_extension_survives_real_project_roundtrip(runtime, tmp_path):
    _app, manager, _meta = runtime
    path = tmp_path / '扩展.qxproj'
    path.write_text(json.dumps({'version': '2.0', 'extension_notes': {'name': '保留'}}), encoding='utf-8')
    assert manager.open_project(str(path))
    assert manager.save_project()
    assert json.loads(path.read_text(encoding='utf-8'))['extension_notes'] == {'name': '保留'}


def test_running_embedded_batch_prevents_switch_without_creating_panel(runtime, monkeypatch):
    _app, manager, _meta = runtime
    runner = SimpleNamespace(isRunning=lambda: True)
    panel = SimpleNamespace(_batch_backend=SimpleNamespace(calculation_runner=runner))
    monkeypatch.setattr(manager, '_iter_project_panel_entries', lambda **kwargs: [('water_profile_panel', panel, '合并面板')])
    with pytest.raises(RuntimeError, match='正在批量计算'):
        manager._require_panels_idle()


def test_close_timeout_keeps_autosave_active_for_remaining_open_window(runtime, monkeypatch):
    _app, manager, _meta = runtime
    manager.start_auto_save()
    with monkeypatch.context() as patch:
        patch.setattr(manager._auto_save_runner, 'wait', lambda timeout: False)
        assert not manager.finish_background_save(1)
        assert manager._auto_save_timer.isActive()


def test_manager_restore_failure_rolls_back_every_critical_state(runtime, tmp_path):
    _app, manager, meta = runtime
    store = {'siphons': {'原数据': {}}}

    def restore(value):
        store.clear()
        store.update(copy.deepcopy(value))
        if '损坏' in value['siphons']:
            raise ValueError('模拟修改内存后恢复失败')

    manager._siphon_manager = SimpleNamespace(to_dict=lambda: copy.deepcopy(store), from_dict=restore)
    manager._current_path = '原工程.qxproj'
    manager.mark_dirty()
    path = tmp_path / '坏工程.qxproj'
    path.write_text(json.dumps({'siphon_manager_data': {'siphons': {'损坏': {}}}}), encoding='utf-8')
    assert not manager.open_project(str(path))
    assert manager.current_path == '原工程.qxproj'
    assert manager.is_dirty
    assert store['siphons'] == {'原数据': {}}
    assert meta[0].project_name == '原工程'
    assert manager.session.generation == 0


def test_report_restore_failure_rolls_back_managers_and_does_not_report_success(runtime, tmp_path, monkeypatch):
    _app, manager, meta = runtime
    store = {'siphons': {'原数据': {}}}
    manager._siphon_manager = SimpleNamespace(
        to_dict=lambda: copy.deepcopy(store),
        from_dict=lambda value: (store.clear(), store.update(copy.deepcopy(value))),
    )
    original_save = report_meta.save_meta

    def fail_new_meta(value):
        original_save(value)
        if value.project_name == '失败工程':
            raise OSError('模拟报告设置写入失败')

    monkeypatch.setattr(report_meta, 'save_meta', fail_new_meta)
    messages = []
    manager.status_message.connect(messages.append)
    path = tmp_path / '坏工程.qxproj'
    path.write_text(json.dumps({'report_meta': {'project_name': '失败工程'}}), encoding='utf-8')
    assert not manager.open_project(str(path))
    assert messages == []
    assert store['siphons'] == {'原数据': {}}
    assert meta[0].project_name == '原工程'


def test_background_autosave_uses_detached_snapshot_and_does_not_clear_new_changes(runtime, tmp_path, monkeypatch):
    app, manager, _meta = runtime
    entered = threading.Event()
    release = threading.Event()
    written = []
    gui_thread = threading.get_ident()
    payload = {'values': [1]}
    path = tmp_path / '自动保存.qxproj'
    monkeypatch.setattr(manager, '_collect_project_data', lambda: payload)
    monkeypatch.setattr(manager, '_get_auto_save_path', lambda: str(path))

    def slow_write(target, data):
        assert threading.get_ident() != gui_thread
        entered.set()
        assert release.wait(3)
        written.append(copy.deepcopy(data))

    monkeypatch.setattr(module, 'atomic_write_json', slow_write)
    manager.mark_dirty()
    manager._do_auto_save()
    assert entered.wait(2)
    ticks = []
    QTimer.singleShot(0, lambda: ticks.append(True))
    app.processEvents()
    assert ticks == [True]
    payload['values'].append(2)
    manager.mark_dirty()
    release.set()
    assert manager.finish_background_save(3000)
    assert written == [{'values': [1]}]
    assert manager.is_dirty
    assert manager.session.revision == 2


def test_new_project_while_autosave_finishes_cannot_apply_old_status(runtime, tmp_path, monkeypatch):
    app, manager, _meta = runtime
    entered = threading.Event()
    release = threading.Event()
    path = tmp_path / '旧工程自动保存.qxproj'
    monkeypatch.setattr(manager, '_get_auto_save_path', lambda: str(path))

    def slow_write(target, data):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(module, 'atomic_write_json', slow_write)
    messages = []
    manager.status_message.connect(messages.append)
    manager.mark_dirty()
    manager._do_auto_save()
    assert entered.wait(2)
    assert manager.new_project()
    release.set()
    assert manager.finish_background_save(3000)
    assert messages == ['已新建项目']
    assert not manager.is_dirty


def test_save_completion_does_not_clear_revision_created_during_save(runtime, tmp_path, monkeypatch):
    _app, manager, _meta = runtime
    manager._current_path = str(tmp_path / '工程.qxproj')
    manager.mark_dirty()
    monkeypatch.setattr(module, 'atomic_write_json', lambda path, payload: manager.mark_dirty())
    assert manager.save_project()
    assert manager.is_dirty
    assert manager.session.revision == 2


def test_report_settings_sync_error_is_a_visible_failure(monkeypatch):
    """QSettings 不抛异常的写入错误也必须进入工程恢复失败分支。"""
    from PySide6.QtCore import QSettings
    fake = SimpleNamespace(
        setValue=lambda *args: None,
        sync=lambda: None,
        status=lambda: QSettings.Status.AccessError,
    )
    monkeypatch.setattr(report_meta, '_qs', lambda: fake)
    with pytest.raises(OSError, match='未能完整写入'):
        report_meta.save_meta(report_meta.ReportMeta())
