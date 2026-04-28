from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import update_helper


def _get_qapp():
    return QApplication.instance() or QApplication([])


def test_main_shows_hint_when_started_without_session(monkeypatch):
    calls: list[str] = []

    def fake_show_hint() -> int:
        calls.append("shown")
        return 0

    monkeypatch.setattr(update_helper, "_show_direct_launch_hint", fake_show_hint)

    result = update_helper.main([])

    assert result == 0
    assert calls == ["shown"]


def test_resolve_window_icon_path_prefers_shared_shield_icon(monkeypatch):
    project_root = Path(tempfile.mkdtemp(prefix="update-helper-icon-"))
    shared_resources = project_root / "app_渠系计算前端" / "resources"
    shared_resources.mkdir(parents=True)
    shield_logo = shared_resources / "license_shield.ico"
    shield_logo.write_bytes(b"shield-logo")
    helper_logo = shared_resources / "update_helper.ico"
    helper_logo.write_bytes(b"legacy-helper-logo")
    (shared_resources / "logo.ico").write_bytes(b"legacy-shared-logo")
    (project_root / "icon.ico").write_bytes(b"legacy-icon")

    monkeypatch.setattr(update_helper.updater, "_get_project_root", lambda: str(project_root))

    assert update_helper._resolve_window_icon_path() == str(shield_logo)


def test_update_helper_surfaces_full_package_guidance_for_patch_mismatch(monkeypatch):
    _get_qapp()
    fake_session = SimpleNamespace(
        current_version="1.0.0",
        target_version="1.1.0",
        work_dir="C:/temp/update-work",
        log_dir="C:/temp/update-logs",
    )

    monkeypatch.setattr(
        update_helper.updater.UpdateSession,
        "from_file",
        lambda _path: fake_session,
    )
    monkeypatch.setattr(update_helper.UpdateHelperWindow, "_start_worker", lambda self: None)

    window = update_helper.UpdateHelperWindow("dummy-session.json")
    window._on_completed(
        {
            "success": False,
            "rollback_ok": False,
            "error_code": "patch_mismatch",
            "user_message": "当前安装状态不适合直接应用补丁，请重新下载完整安装包后再试。",
            "retry_mode": update_helper.updater.RETRY_MODE_FULL_PACKAGE,
            "error": "本机文件状态与补丁预期不一致",
            "log_path": "C:/temp/update-logs/install.log",
        }
    )

    assert "完整安装包" in window.status_label.text()
    assert "重新下载完整安装包" in window.footer_label.text()
    assert window.btn_retry.text() == "重新下载完整安装包"
    window.close()


def test_update_helper_expands_failure_window_to_keep_stage_lines_readable(monkeypatch):
    app = _get_qapp()
    fake_session = SimpleNamespace(
        current_version="1.0.0",
        target_version="1.1.0",
        work_dir="C:/temp/update-work",
        log_dir="C:/temp/update-logs",
    )

    monkeypatch.setattr(
        update_helper.updater.UpdateSession,
        "from_file",
        lambda _path: fake_session,
    )
    monkeypatch.setattr(update_helper.UpdateHelperWindow, "_start_worker", lambda self: None)

    window = update_helper.UpdateHelperWindow("dummy-session.json")
    initial_height = window.height()

    window._on_completed(
        {
            "success": False,
            "rollback_ok": False,
            "error_code": "patch_mismatch",
            "user_message": "当前安装状态不适合直接应用补丁，请重新下载完整安装包后再试。",
            "retry_mode": update_helper.updater.RETRY_MODE_FULL_PACKAGE,
            "error": "本机文件状态与补丁预期不一致",
            "log_path": "C:/temp/update-logs/install.log",
        }
    )
    window.show()
    app.processEvents()

    stage_heights = [label.height() for label in window._stage_labels.values()]
    assert window.height() > initial_height
    assert min(stage_heights) >= 15
    assert window.result_stage_label.height() >= 15
    window.close()


def test_update_helper_shows_patch_validation_progress_text(monkeypatch):
    _get_qapp()
    fake_session = SimpleNamespace(
        current_version="1.3.0",
        target_version="1.3.4",
        work_dir="C:/temp/update-work",
        log_dir="C:/temp/update-logs",
    )

    monkeypatch.setattr(
        update_helper.updater.UpdateSession,
        "from_file",
        lambda _path: fake_session,
    )
    monkeypatch.setattr(update_helper.UpdateHelperWindow, "_start_worker", lambda self: None)

    window = update_helper.UpdateHelperWindow("dummy-session.json")
    window._on_stage_changed("validate", "正在校验补丁适用性（2/5）")

    assert "正在校验补丁适用性（2/5）" in window.status_label.text()
    assert "正在校验补丁适用性（2/5）" in window.detail_text.toPlainText()
    window.close()


def test_update_helper_shows_cleanup_and_full_package_validate_text(monkeypatch):
    _get_qapp()
    fake_session = SimpleNamespace(
        current_version="1.2.5",
        target_version="1.2.6",
        work_dir="C:/temp/update-work",
        log_dir="C:/temp/update-logs",
    )

    monkeypatch.setattr(
        update_helper.updater.UpdateSession,
        "from_file",
        lambda _path: fake_session,
    )
    monkeypatch.setattr(update_helper.UpdateHelperWindow, "_start_worker", lambda self: None)

    window = update_helper.UpdateHelperWindow("dummy-session.json")
    window._on_stage_changed("validate", "正在清理上次失败残留")
    assert "正在清理上次失败残留" in window.status_label.text()
    assert "正在清理上次失败残留" in window.detail_text.toPlainText()

    window._on_stage_changed("validate", "正在统计安装目录大小（已扫描 12 个文件）")
    assert "正在统计安装目录大小（已扫描 12 个文件）" in window.status_label.text()
    assert "正在统计安装目录大小（已扫描 12 个文件）" in window.detail_text.toPlainText()

    window._on_stage_changed("validate", "正在解压完整安装包（14/120）")
    assert "正在解压完整安装包（14/120）" in window.status_label.text()
    assert "正在解压完整安装包（14/120）" in window.detail_text.toPlainText()
    window.close()


def test_update_helper_surfaces_stale_session_cleanup_guidance(monkeypatch):
    _get_qapp()
    fake_session = SimpleNamespace(
        current_version="1.2.5",
        target_version="1.2.6",
        work_dir="C:/temp/update-work",
        log_dir="C:/temp/update-logs",
    )

    monkeypatch.setattr(
        update_helper.updater.UpdateSession,
        "from_file",
        lambda _path: fake_session,
    )
    monkeypatch.setattr(update_helper.UpdateHelperWindow, "_start_worker", lambda self: None)

    window = update_helper.UpdateHelperWindow("dummy-session.json")
    window._on_completed(
        {
            "success": False,
            "rollback_ok": False,
            "error_code": "stale_session_cleanup_failed",
            "user_message": "检测到上次失败留下的临时更新文件，但当前无法清理。请关闭软件后重试；如仍失败，请重启电脑后再试。",
            "retry_mode": None,
            "error": "无法清理旧更新会话目录：C:/temp/update-work/stale-session",
            "log_path": "C:/temp/update-logs/install.log",
        }
    )

    assert "关闭软件后重试" in window.status_label.text()
    assert "重启电脑后再试" in window.guidance_body_label.text()
    assert not window.btn_open_log.isHidden()
    assert not window.btn_retry.isHidden()
    window.close()


def test_update_helper_distinguishes_no_rollback_needed(monkeypatch):
    _get_qapp()
    fake_session = SimpleNamespace(
        current_version="1.2.5",
        target_version="1.2.6",
        work_dir="C:/temp/update-work",
        log_dir="C:/temp/update-logs",
    )

    monkeypatch.setattr(
        update_helper.updater.UpdateSession,
        "from_file",
        lambda _path: fake_session,
    )
    monkeypatch.setattr(update_helper.UpdateHelperWindow, "_start_worker", lambda self: None)

    window = update_helper.UpdateHelperWindow("dummy-session.json")
    window._on_completed(
        {
            "success": False,
            "rollback_ok": False,
            "rollback_status": "not_needed",
            "error_code": "prepare_failed",
            "user_message": "",
            "retry_mode": None,
            "error": "backup not started",
            "log_path": "C:/temp/update-logs/install.log",
        }
    )

    assert "回滚未完成" not in window.status_label.text()
    assert "回滚未完成" not in window.result_stage_label.text()
    window.close()


def test_update_helper_shows_cleanup_warning_after_success(monkeypatch):
    _get_qapp()
    fake_session = SimpleNamespace(
        current_version="1.2.5",
        target_version="1.2.6",
        work_dir="C:/temp/update-work",
        log_dir="C:/temp/update-logs",
    )

    monkeypatch.setattr(
        update_helper.updater.UpdateSession,
        "from_file",
        lambda _path: fake_session,
    )
    monkeypatch.setattr(update_helper.UpdateHelperWindow, "_start_worker", lambda self: None)

    window = update_helper.UpdateHelperWindow("dummy-session.json")
    window._on_completed(
        {
            "success": True,
            "cleanup_errors": ["无法删除临时目录：C:/temp/update-work/extract"],
            "log_path": "C:/temp/update-logs/install.log",
        }
    )

    assert "未清理" in window.footer_label.text()
    window.close()
