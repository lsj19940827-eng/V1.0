"""旁文件与独立工况共享原子写入，不因失败截断原件。"""

import json

import pytest

import atomic_json
from app_渠系计算前端.siphon.case_manager import CaseManager
from 推求水面线.managers.pressure_pipe_manager import PressurePipeManager
from 推求水面线.managers.siphon_manager import SiphonManager


@pytest.mark.parametrize('manager_class, suffix, bucket', [
    (PressurePipeManager, '.ppipe.json', 'pipes'),
    (SiphonManager, '.siphon.json', 'siphons'),
])
def test_binding_path_never_reads_or_replaces_current_state(tmp_path, manager_class, suffix, bucket):
    path = tmp_path / '工程.qxproj'
    path.with_suffix(suffix).write_text(json.dumps({bucket: {'旧旁文件': {}}}), encoding='utf-8')
    manager = manager_class(load_existing=False)
    manager.from_dict({bucket: {'当前输入': {}}})
    manager.bind_project_path(str(path))
    assert manager.to_dict()[bucket] == {'当前输入': {}}
    manager.load_config()
    assert manager.to_dict()[bucket] == {'旧旁文件': {}}


@pytest.mark.parametrize('manager_class, suffix', [
    (PressurePipeManager, '.ppipe.json'), (SiphonManager, '.siphon.json'),
])
def test_failed_sidecar_save_propagates_and_preserves_original(tmp_path, monkeypatch, manager_class, suffix):
    path = tmp_path / '工程.qxproj'
    target = path.with_suffix(suffix)
    target.write_bytes(b'{"original": true}')
    manager = manager_class(load_existing=False)
    manager.bind_project_path(str(path))

    def fail(*args):
        raise PermissionError('模拟占用')

    monkeypatch.setattr(atomic_json.os, 'replace', fail)
    with pytest.raises(PermissionError, match='模拟占用'):
        manager.save_config()
    assert target.read_bytes() == b'{"original": true}'
    assert list(tmp_path.iterdir()) == [target]


def test_case_serialization_failure_preserves_original_and_input(tmp_path):
    manager = CaseManager(str(tmp_path))
    case = manager.create_case('原工况')
    from pathlib import Path
    path = Path(case.file_path)
    original = path.read_bytes()
    payload = {'invalid': object()}
    with pytest.raises(TypeError):
        manager.save_case_data(case, payload)
    assert list(payload) == ['invalid']
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('broken', ['{不完整', '[]', '{"order": "坏顺序"}'])
def test_case_load_keeps_valid_cases_and_exposes_broken_files(tmp_path, broken):
    manager = CaseManager(str(tmp_path))
    manager.create_case('正常工况')
    (tmp_path / '坏工况.siphon.json').write_text(broken, encoding='utf-8')
    reloaded = CaseManager(str(tmp_path))
    assert [case.name for case in reloaded.cases] == ['正常工况']
    assert len(reloaded.load_errors) == 1
    assert reloaded.load_errors[0]['path'].endswith('坏工况.siphon.json')
    assert reloaded.load_errors[0]['message']
