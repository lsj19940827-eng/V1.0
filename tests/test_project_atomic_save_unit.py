"""工程保存失败时保留原文件，不能静默漏存模块数据。"""

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app_渠系计算前端 import project_manager as module


@pytest.fixture
def manager():
    """提供未绑定实际工程的管理器。"""
    app = QApplication.instance() or QApplication([])
    instance = module.ProjectManager()
    yield instance
    instance.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("failure", ["serialization", "replace"])
def test_failed_write_preserves_original_project_and_cleans_temp(manager, tmp_path, monkeypatch, failure):
    """序列化中途失败、替换被拒绝时，原工程逐字节不变且仍是未保存状态。"""
    path = tmp_path / "测试工程.qxproj"
    original = '{"version": "旧工程", "data": [1, 2, 3]}'.encode("utf-8")
    path.write_bytes(original)
    payload = {"valid": "前半段", "value": object() if failure == "serialization" else [4, 5]}
    monkeypatch.setattr(manager, "_collect_project_data", lambda: payload)
    if failure == "replace":
        def deny_replace(*_args):
            """模拟目标文件被占用或无权替换。"""
            raise PermissionError("模拟文件被占用")
        monkeypatch.setattr(module.os, "replace", deny_replace)
    errors = []
    messages = []
    monkeypatch.setattr(module.QMessageBox, "critical", lambda *_args: errors.append(_args[-1]))
    manager.status_message.connect(messages.append)
    manager._current_path = str(path)
    manager.mark_dirty()
    assert manager.save_project() is False
    assert len(errors) == 1
    assert messages == []
    assert path.read_bytes() == original
    assert manager.is_dirty
    assert list(tmp_path.iterdir()) == [path]


def test_successful_write_preserves_project_payload(manager, tmp_path, monkeypatch):
    """成功保存保留中文、数值精度与原有 JSON 结构。"""
    path = tmp_path / "工程.qxproj"
    payload = {"version": "2.0", "name": "茶亭支渠", "values": [0.123456789012345, None]}
    monkeypatch.setattr(manager, "_collect_project_data", lambda: payload)
    manager._save_to_file(str(path))
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert list(tmp_path.iterdir()) == [path]


def test_panel_collection_failure_does_not_save_partial_project(manager, tmp_path, monkeypatch):
    """任何已存在模块读取失败时，阻止用缺少该模块的新文件覆盖旧工程。"""
    def fail_collection():
        """模拟面板数据收集异常。"""
        raise ValueError("模拟工况数据损坏")
    broken = SimpleNamespace(to_project_dict=fail_collection)
    monkeypatch.setattr(manager, "_get_panel", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "_iter_project_panel_entries", lambda **_kwargs: [
        ("pressure_pipe_panel", broken, "有压管道")
    ])
    path = tmp_path / "工程.qxproj"
    path.write_text("旧工程内容", encoding="utf-8")
    with pytest.raises(RuntimeError, match="有压管道.*模拟工况数据损坏"):
        manager._save_to_file(str(path))
    assert path.read_text(encoding="utf-8") == "旧工程内容"
    assert list(tmp_path.iterdir()) == [path]
