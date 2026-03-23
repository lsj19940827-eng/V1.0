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


def test_resolve_window_icon_path_prefers_shared_logo(monkeypatch):
    project_root = Path(tempfile.mkdtemp(prefix="update-helper-icon-"))
    shared_resources = project_root / "app_渠系计算前端" / "resources"
    shared_resources.mkdir(parents=True)
    shared_logo = shared_resources / "logo.ico"
    shared_logo.write_bytes(b"shield-logo")
    (project_root / "icon.ico").write_bytes(b"legacy-icon")

    monkeypatch.setattr(update_helper.updater, "_get_project_root", lambda: str(project_root))

    assert update_helper._resolve_window_icon_path() == str(shared_logo)


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
