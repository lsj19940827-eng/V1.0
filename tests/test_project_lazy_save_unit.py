"""保存不创建未访问页面，并验证稀疏工程重开、重置与恢复失败保护。"""

import copy
import importlib
import json
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('CODEX_FORCE_QTEXTBROWSER', '1')

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QWidget, QTableWidgetItem

from app_渠系计算前端.panel_registry import PanelDescriptor, PanelRegistry
from app_渠系计算前端 import project_manager as module


@pytest.fixture(autouse=True)
def isolated_report_settings(monkeypatch):
    """工程恢复测试只使用内存中的报告设置，不改写用户配置。"""
    from app_渠系计算前端 import report_meta
    state = [report_meta.ReportMeta()]
    monkeypatch.setattr(report_meta, 'load_meta', lambda: copy.deepcopy(state[0]))
    monkeypatch.setattr(report_meta, 'save_meta', lambda value: state.__setitem__(0, copy.deepcopy(value)))


class _Panel(QWidget):
    data_changed = Signal()

    def __init__(self):
        super().__init__()
        self.state = {'input': '', 'results': [], 'ui': {'name': ''}}

    def to_project_dict(self):
        return copy.deepcopy(self.state)

    def from_project_dict(self, data, **kwargs):
        if data.get('invalid'):
            raise ValueError('模拟不兼容数据')
        self.state.update(copy.deepcopy(data))
        self.data_changed.emit()


@pytest.fixture
def runtime(monkeypatch):
    app = QApplication.instance() or QApplication([])
    created = []

    def factory(key):
        created.append(key)
        return _Panel()

    slots = ('open_channel', 'pressure_pipe', 'water_profile')
    registry = PanelRegistry([
        PanelDescriptor(key, key, i, key + '_panel', lambda key=key: factory(key), key + '_panel')
        for i, key in enumerate(slots)
    ])
    registry.get('open_channel')
    manager = module.ProjectManager()
    manager.bind_runtime(registry)
    monkeypatch.setattr(manager, '_add_recent_project', lambda path: None)
    monkeypatch.setattr(manager, '_check_save_before_close', lambda: True)
    yield manager, registry, created
    for panel in registry.iter_instances():
        panel.deleteLater()
    manager.deleteLater()
    registry.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('mode', ['save', 'save_as', 'auto'])
def test_all_save_entries_keep_unvisited_panels_uncreated(runtime, tmp_path, monkeypatch, mode):
    manager, registry, created = runtime
    panel = registry.get_existing('open_channel')
    panel.state['input'] = '中文参数 0.123456789012345'
    panel.state['results'] = [{'value': 0.123456789012345}]
    path = tmp_path / '工程.qxproj'
    manager.mark_dirty()
    if mode == 'save':
        manager._current_path = str(path)
        assert manager.save_project()
    elif mode == 'save_as':
        monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), ''))
        assert manager.save_as_project()
    else:
        monkeypatch.setattr(manager, '_get_auto_save_path', lambda: str(path))
        manager._do_auto_save()
        assert manager.finish_background_save(5000)
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert created == ['open_channel']
    assert saved['open_channel_panel'] == panel.state
    assert saved['water_profile_panel'] is None
    assert saved['pressure_pipe_panel'] is None


def test_open_sparse_project_resets_existing_module_and_preserves_present_payload(runtime, tmp_path):
    manager, registry, created = runtime
    registry.get('pressure_pipe').state['input'] = '上一工程的管道'
    registry.get('water_profile').state['results'] = ['上一工程结果']
    saved = {'open_channel_panel': {'input': '当前工程', 'results': [1.23456789]}}
    manager._restore_project_data(saved)
    assert registry.get('pressure_pipe').state['input'] == ''
    assert registry.get('water_profile').state['results'] == []
    assert registry.get('open_channel').state['input'] == '当前工程'
    assert not manager.is_dirty
    path = tmp_path / '重存.qxproj'
    manager._save_to_file(str(path))
    actual = json.loads(path.read_text(encoding='utf-8'))
    assert actual['open_channel_panel']['results'] == [1.23456789]


def test_new_project_resets_existing_only_and_binds_path_without_loading_sidecar(runtime):
    manager, registry, created = runtime
    registry.get_existing('open_channel').state['results'] = ['旧结果']
    service_data = []
    bound_paths = []
    manager._siphon_manager = SimpleNamespace(
        from_dict=lambda value: service_data.append(copy.deepcopy(value)),
        to_dict=lambda: {'siphons': {'旧状态': {}}},
        bind_project_path=bound_paths.append,
    )
    assert manager.new_project()
    assert created == ['open_channel']
    assert registry.get_existing('open_channel').state['results'] == []
    assert service_data[-1]['siphons'] == {}
    assert bound_paths == ['']


@pytest.mark.parametrize('empty', [None, {}])
def test_open_does_not_create_modules_with_no_saved_data(runtime, empty):
    manager, registry, created = runtime
    manager._restore_project_data({'open_channel_panel': {'input': '保留值'},
                                   'pressure_pipe_panel': empty, 'water_profile_panel': empty})
    assert created == ['open_channel']
    assert registry.get('open_channel').state['input'] == '保留值'
    assert manager._collect_project_data()['pressure_pipe_panel'] is None


def test_open_creates_and_restores_unvisited_module_when_payload_exists(runtime):
    manager, registry, created = runtime
    payload = {'input': '从未访问的管道', 'results': [0.123456789012345]}
    manager._restore_project_data({'pressure_pipe_panel': payload})
    assert created == ['open_channel', 'pressure_pipe']
    assert registry.get('pressure_pipe').state['results'] == payload['results']
    assert manager._collect_project_data()['pressure_pipe_panel']['input'] == payload['input']


def test_invalid_module_shape_fails_before_changing_existing_inputs(runtime):
    manager, registry, created = runtime
    panel = registry.get('open_channel')
    panel.state['input'] = '原始数据'
    with pytest.raises(ValueError, match='JSON 对象'):
        manager._restore_project_data({'open_channel_panel': [], 'pressure_pipe_panel': {'input': '新'}})
    assert panel.state['input'] == '原始数据'
    assert created == ['open_channel']


def test_empty_module_first_visit_after_open_uses_clean_defaults(runtime):
    manager, registry, created = runtime
    manager._restore_project_data({})
    assert 'pressure_pipe_panel' in manager._reset_on_first_visit
    registry.get('pressure_pipe')
    assert 'pressure_pipe_panel' not in manager._reset_on_first_visit
    assert not manager.is_dirty


def test_failed_open_restores_previous_inputs_and_does_not_change_path(runtime, tmp_path):
    manager, registry, created = runtime
    registry.get('open_channel').state['input'] = '原工程未保存输入'
    manager._current_path = '原工程.qxproj'
    manager.mark_dirty()
    path = tmp_path / '损坏.qxproj'
    path.write_text(json.dumps({'pressure_pipe_panel': {'invalid': True}}), encoding='utf-8')
    with pytest.raises(RuntimeError, match='不兼容数据'):
        manager._load_from_file(str(path))
    assert registry.get('open_channel').state['input'] == '原工程未保存输入'
    assert manager.current_path == '原工程.qxproj'
    assert manager.is_dirty
    assert not manager._project_restore_error


def test_running_batch_prevents_project_switch_without_touching_inputs(runtime, tmp_path):
    manager, registry, created = runtime
    panel = registry.get('pressure_pipe')
    panel.state['input'] = '计算中'
    panel._batch_worker = SimpleNamespace(isRunning=lambda: True)
    path = tmp_path / '空工程.qxproj'
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(RuntimeError, match='正在批量计算'):
        manager._load_from_file(str(path))
    assert panel.state['input'] == '计算中'
    assert registry.get_existing('water_profile') is None


def test_batch_only_legacy_project_is_forwarded_to_merged_panel(runtime):
    manager, registry, created = runtime
    legacy = {'input_rows': [['旧版断面']], 'flow_segments': '1.25'}
    manager._restore_project_data({'batch_panel': legacy})
    assert registry.get('water_profile').state['batch_panel_compat'] == legacy


def test_failed_rollback_blocks_writes_until_project_recovers(runtime, tmp_path, monkeypatch):
    manager, registry, created = runtime
    panel = registry.get('open_channel')
    original = panel.from_project_dict

    def fail(*args, **kwargs):
        raise ValueError('模拟持续恢复失败')

    monkeypatch.setattr(panel, 'from_project_dict', fail)
    path = tmp_path / '工程.qxproj'
    path.write_text('{}', encoding='utf-8')
    with pytest.raises(RuntimeError, match='已暂停保存'):
        manager._load_from_file(str(path))
    with pytest.raises(RuntimeError, match='尚未完整恢复'):
        manager._save_to_file(str(path))
    assert path.read_text(encoding='utf-8') == '{}'
    monkeypatch.setattr(panel, 'from_project_dict', original)
    manager._load_from_file(str(path))
    assert manager._project_restore_error == ''
    manager._save_to_file(str(path))


def test_real_legacy_batch_project_restores_global_inputs_and_can_be_resaved(tmp_path):
    """旧文件中的渠道信息须进入可见合并界面，不能只恢复到隐藏批量后端。"""
    app = QApplication.instance() or QApplication([])
    from app_渠系计算前端.water_profile.panel import WaterProfilePanel
    registry = PanelRegistry([PanelDescriptor(
        'water_profile', '水面线', 0, 'water_profile_panel', WaterProfilePanel, 'water_profile_panel'
    )])
    manager = module.ProjectManager()
    manager.bind_runtime(registry)
    legacy = {
        'channel_name': '旧版渠道', 'channel_level': '支渠', 'start_water_level': '125.6789',
        'start_station': '20.125', 'flow_segments': '1.25, 0.85', 'input_rows': [['1']],
    }
    try:
        manager._restore_project_data({'batch_panel': legacy})
        panel = registry.get('water_profile')
        assert panel.channel_name_edit.text() == '旧版渠道'
        assert panel.start_wl_edit.text() == '125.6789'
        assert panel.start_station_edit.text() == '20.125'
        assert panel._section_input_table.rowCount() == 1
        assert panel.design_flow_edit.text() == '1.25, 0.85'
        saved = manager._collect_project_data()
        assert saved['merged_panel']['ui_settings']['channel_name'] == '旧版渠道'
        assert saved['batch_panel']['start_water_level'] == '125.6789'
    finally:
        panel.deleteLater()
        manager.deleteLater()
        registry.deleteLater()
        app.processEvents()


def test_real_empty_water_panel_first_visit_after_open_has_no_startup_example():
    app = QApplication.instance() or QApplication([])
    from app_渠系计算前端.water_profile.panel import WaterProfilePanel
    registry = PanelRegistry([PanelDescriptor(
        'water_profile', '水面线', 0, 'water_profile_panel', WaterProfilePanel, 'water_profile_panel'
    )])
    manager = module.ProjectManager()
    manager.bind_runtime(registry)
    manager._restore_project_data({})
    assert registry.get_existing('water_profile') is None
    panel = registry.get('water_profile')
    try:
        assert panel.channel_name_edit.text() == ''
        assert panel.start_wl_edit.text() == ''
        assert panel.design_flow_edit.text() == ''
        assert panel._section_input_table.rowCount() == 0
        assert not manager.is_dirty
    finally:
        panel.deleteLater()
        manager.deleteLater()
        registry.deleteLater()
        app.processEvents()


@pytest.mark.parametrize('key, class_name', [
    ('open_channel', 'OpenChannelPanel'), ('aqueduct', 'AqueductPanel'),
    ('tunnel', 'TunnelPanel'), ('culvert', 'CulvertPanel'),
    ('pressure_pipe', 'PressurePipePanel'), ('water_profile', 'WaterProfilePanel'),
    ('siphon', 'SiphonPanel'), ('spillway_steep_chute', 'SpillwaySteepChutePanel'),
])
def test_real_panels_reset_current_project_state(key, class_name, monkeypatch, tmp_path):
    """真实面板上验证空输入恢复与结果清除，不依赖假控件序列化。"""
    app = QApplication.instance() or QApplication([])
    panel_module = importlib.import_module(f'app_渠系计算前端.{key}.panel')
    if key == 'siphon':
        # 工况管理使用独立测试目录，不读取或写回用户的独立工况文件。
        monkeypatch.setattr(panel_module, '_pkg_root', str(tmp_path))
    cls = getattr(panel_module, class_name)
    kwargs = {'disable_autosave_load': True} if key == 'siphon' else {}
    registry = PanelRegistry([PanelDescriptor(key, key, 0, key + '_panel', lambda: cls(**kwargs), key + '_panel')])
    manager = module.ProjectManager()
    manager.bind_runtime(registry)
    panel = registry.get(key)
    defaults = copy.deepcopy(manager._initial_panel_data[key + '_panel'])
    try:
        if key == 'water_profile':
            panel.channel_name_edit.setText('旧渠道')
            panel.start_wl_edit.setText('123.4')
            panel.design_flow_edit.setText('8.5')
            panel._loss_undo_stack.append({'旧快照': True})
            panel._batch_backend._table_undo_stack.append({'旧行': True})
            panel._section_input_table.setRowCount(1)
            panel._section_input_table.setItem(0, 1, QTableWidgetItem('旧断面'))
        elif key == 'siphon':
            panel.edit_threshold.setText('123')
            panel.edit_v1.setText('3.5')
            panel.edit_v_out.setText('2.8')
            panel.calculation_result = SimpleNamespace(total_head_loss=8.2, diameter=1.4, velocity=1.8)
            panel.summary_text.setPlainText('旧计算结果')
        else:
            panel._cases.append(copy.deepcopy(panel._cases[0]))
            panel._all_results = [('旧结果',)]
            panel.current_result = {'旧': True}
        manager._reset_panels()
        assert registry.get(key) is panel
        if key == 'water_profile':
            assert panel.channel_name_edit.text() == defaults['ui_settings']['channel_name']
            assert panel.start_wl_edit.text() == defaults['ui_settings']['start_water_level']
            assert panel.design_flow_edit.text() == defaults['ui_settings']['design_flows_text']
            assert panel._section_input_table.rowCount() == 0
            assert panel._loss_undo_stack == panel._batch_backend._table_undo_stack == []
            assert panel.channel_name_edit.text() == panel.start_wl_edit.text() == ''
            assert panel.design_flow_edit.text() == panel.max_flow_edit.text() == ''
            assert panel.start_station_edit.text() == '0'
            assert panel.roughness_edit.text() == '0.017'
            assert panel.channel_level_combo.currentIndex() == 0
        elif key == 'siphon':
            assert panel.edit_threshold.text() == defaults['threshold']
            assert panel.edit_v1.text() == defaults['v1']
            assert panel.edit_v_out.text() == defaults['v_out']
            assert panel.calculation_result is None
            assert panel.summary_text.toPlainText() == ''
        else:
            assert len(panel._cases) == 1
            assert panel._all_results == []
            assert panel.current_result is None
    finally:
        timer = getattr(panel, '_autosave_timer', None)
        if timer is not None:
            timer.stop()
        panel.deleteLater()
        manager.deleteLater()
        registry.deleteLater()
        app.processEvents()
