"""工程格式和会话的纯数据行为契约。"""

import copy
import json

import pytest

from app_渠系计算前端.project_codec import ProjectCodec, ProjectFormatError
from app_渠系计算前端.project_session import ProjectSession


def test_legacy_batch_migrates_without_changing_source():
    source = {'batch_panel': {'channel_name': '旧工程', 'start_station': '12.345', 'flow_segments': '1.2'}}
    before = copy.deepcopy(source)
    result = ProjectCodec.normalize(source)
    assert source == before
    assert result['merged_panel']['ui_settings'] == {
        'channel_name': '旧工程', 'start_station_text': '12.345', 'design_flows_text': '1.2',
    }
    assert result['water_profile_panel'] == result['merged_panel']
    assert result['siphon_manager_data']['siphons'] == {}
    assert result['report_meta']['project_name'] == ''
    assert ProjectCodec.normalize(result) == result


@pytest.mark.parametrize('payload, message', [
    ({'version': '99.0'}, '高于当前支持'),
    ({'version': '损坏'}, '版本格式无效'),
    ({'pressure_pipe_manager_data': []}, 'JSON 对象'),
    ({'siphon_manager_data': {'siphons': {'错误': 1}}}, 'JSON 对象'),
    ({'report_meta': {'extra_references': [42]}}, '文本列表'),
    ({'report_meta': {'project_name': 123}}, '必须是文本'),
    ({'report_meta': {'future_field': '新版本内容'}}, '未支持字段'),
    ({'water_profile_panel': {'ui_settings': []}}, 'JSON 对象'),
    ({'water_profile_panel': {'version': '2.0'}}, '高于当前支持'),
    ({'water_profile_panel': {'nodes': [None]}}, '由对象组成的列表'),
    ({'water_profile_panel': {'table_state': []}}, 'table_state 无效'),
    ({'water_profile_panel': {'table_state': {'version': 2}}}, 'table_state 无效'),
    ({'water_profile_panel': {'table_state': {'rows': [{'cell_data': {'坏键': 1}}]}}}, 'table_state 无效'),
])
def test_invalid_or_future_data_rejected_before_runtime(payload, message):
    with pytest.raises(ProjectFormatError, match=message):
        ProjectCodec.normalize(payload)


def test_sidecar_import_only_for_missing_embedded_data(tmp_path):
    path = tmp_path / '工程.qxproj'
    sidecar = tmp_path / '工程.ppipe.json'
    sidecar.write_text(json.dumps({'pipes': {'旧旁文件': {}}}), encoding='utf-8')
    path.write_text('{}', encoding='utf-8')
    assert '旧旁文件' in ProjectCodec.read(str(path))['pressure_pipe_manager_data']['pipes']
    # 显式空对象也表示当前工程选择，不能被旁文件反向覆盖。
    path.write_text(json.dumps({'pressure_pipe_manager_data': {}}), encoding='utf-8')
    assert ProjectCodec.read(str(path))['pressure_pipe_manager_data']['pipes'] == {}


def test_malformed_legacy_sidecar_is_not_silently_discarded(tmp_path):
    path = tmp_path / '工程.qxproj'
    path.write_text('{}', encoding='utf-8')
    (tmp_path / '工程.siphon.json').write_text('{错误', encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):
        ProjectCodec.read(str(path))


def test_session_snapshot_is_detached_and_old_revision_cannot_clear_new_changes():
    session = ProjectSession()
    payload = {'inputs': [1]}
    snapshot = session.capture(payload)
    payload['inputs'].append(2)
    assert snapshot.data == {'inputs': [1]}
    session.changed()
    assert not session.confirm_saved(snapshot)
    current = session.capture(payload)
    assert session.confirm_saved(current)
    session.commit({'inputs': [3]}, '新工程.qxproj')
    assert not session.confirm_saved(current)


def test_unknown_same_version_top_level_fields_survive_normalization():
    data = ProjectCodec.normalize({'version': '2.0', 'extension_notes': {'source': '原样保留'}})
    assert data['extension_notes'] == {'source': '原样保留'}
