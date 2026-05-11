# -*- coding: utf-8 -*-
"""更新窗口安装前保存拦截逻辑测试。"""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


def _qt_app():
    """返回测试可复用的 QApplication。"""
    return QApplication.instance() or QApplication([])


class _ProjectManagerStub:
    """模拟项目管理器的脏状态和保存结果。"""

    def __init__(self, *, dirty: bool, save_result: bool = True):
        self.is_dirty = dirty
        self.save_result = save_result
        self.save_calls = 0

    def save_project(self) -> bool:
        """记录保存次数，并按测试指定结果返回。"""
        self.save_calls += 1
        if self.save_result:
            self.is_dirty = False
        return self.save_result


def _dialog(monkeypatch, *, dirty: bool, save_result: bool = True):
    """创建带项目管理器的更新窗口。"""
    _qt_app()
    from app_渠系计算前端.update_dialog import UpdateDialog
    import updater

    parent = QWidget()
    project_manager = _ProjectManagerStub(dirty=dirty, save_result=save_result)
    parent.project_manager = project_manager
    dialog = UpdateDialog(parent)
    dialog._test_parent_ref = parent
    dialog._zip_path = r"C:\temp\CanalHydraulicCalc-update.zip"
    dialog._is_patch = False
    dialog._update_info = SimpleNamespace(
        download_sha256="full-sha",
        patch_sha256="patch-sha",
    )

    checked = []
    monkeypatch.setattr(
        updater,
        "ensure_update_package_ready",
        lambda path, sha: checked.append((path, sha)) or {"zip_path": path},
    )
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *_a, **_k: None))
    return UpdateDialog, dialog, project_manager, checked


def test_dirty_project_can_save_and_continue_install(monkeypatch):
    """未保存项目选择保存后，应继续校验已下载更新包。"""
    UpdateDialog, dialog, project_manager, checked = _dialog(monkeypatch, dirty=True)

    confirm_calls = []
    monkeypatch.setattr(
        UpdateDialog,
        "_confirm_save_before_install",
        lambda self: confirm_calls.append(True) or True,
        raising=False,
    )

    assert dialog._validate_before_install() is True
    assert confirm_calls == [True]
    assert project_manager.save_calls == 1
    assert dialog._zip_path == r"C:\temp\CanalHydraulicCalc-update.zip"
    assert checked == [(r"C:\temp\CanalHydraulicCalc-update.zip", "full-sha")]


def test_dirty_project_cancel_save_keeps_downloaded_package(monkeypatch):
    """用户暂不保存时，应停留在窗口并保留已下载包。"""
    UpdateDialog, dialog, project_manager, checked = _dialog(monkeypatch, dirty=True)

    confirm_calls = []
    monkeypatch.setattr(
        UpdateDialog,
        "_confirm_save_before_install",
        lambda self: confirm_calls.append(True) and False,
        raising=False,
    )

    assert dialog._validate_before_install() is False
    assert confirm_calls == [True]
    assert project_manager.save_calls == 0
    assert dialog._zip_path == r"C:\temp\CanalHydraulicCalc-update.zip"
    assert checked == []


def test_dirty_project_save_failure_keeps_downloaded_package(monkeypatch):
    """保存失败时，不进入安装，但仍保留已下载包供重试。"""
    UpdateDialog, dialog, project_manager, checked = _dialog(
        monkeypatch,
        dirty=True,
        save_result=False,
    )

    confirm_calls = []
    monkeypatch.setattr(
        UpdateDialog,
        "_confirm_save_before_install",
        lambda self: confirm_calls.append(True) or True,
        raising=False,
    )

    assert dialog._validate_before_install() is False
    assert confirm_calls == [True]
    assert project_manager.save_calls == 1
    assert dialog._zip_path == r"C:\temp\CanalHydraulicCalc-update.zip"
    assert checked == []


def test_saved_project_installs_without_extra_save_prompt(monkeypatch):
    """项目已保存时，应保持原有安装前校验流程。"""
    UpdateDialog, dialog, project_manager, checked = _dialog(monkeypatch, dirty=False)

    monkeypatch.setattr(
        UpdateDialog,
        "_confirm_save_before_install",
        lambda self: (_ for _ in ()).throw(AssertionError("不应询问保存")),
        raising=False,
    )

    assert dialog._validate_before_install() is True
    assert project_manager.save_calls == 0
    assert checked == [(r"C:\temp\CanalHydraulicCalc-update.zip", "full-sha")]
