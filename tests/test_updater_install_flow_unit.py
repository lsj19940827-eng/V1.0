from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

import updater


def _make_full_zip(zip_path: Path, version: str, files: dict[str, str]) -> Path:
    root_name = f"{updater.APP_NAME_EN}-V{version}"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in files.items():
            zf.writestr(f"{root_name}/{rel_path}", content)
    return zip_path


def _make_patch_zip(
    zip_path: Path,
    *,
    included_files: dict[str, str],
    deleted: list[str] | None = None,
    allowed_source_hashes: dict[str, list[str]] | None = None,
    min_version: str = "1.0.0",
) -> Path:
    manifest = {
        "type": "universal_patch",
        "version": "9.9.9",
        "min_version": min_version,
        "included_files": sorted(included_files.keys()),
        "deleted": deleted or [],
        "allowed_source_hashes": allowed_source_hashes or {},
    }
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("patch_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for rel_path, content in included_files.items():
            zf.writestr(rel_path, content)
    return zip_path


def _write_session(
    tmp_path: Path,
    *,
    app_dir: Path,
    zip_path: Path,
    is_patch: bool,
    session_id: str = "session-001",
) -> str:
    log_dir = tmp_path / "logs" / session_id
    session = updater.UpdateSession(
        session_id=session_id,
        app_dir=str(app_dir),
        main_exe_path=str(app_dir / f"{updater.APP_NAME_EN}.exe"),
        download_zip_path=str(zip_path),
        is_patch=is_patch,
        target_version="9.9.9",
        current_version="1.0.0",
        log_dir=str(log_dir),
        cleanup_targets=[],
        preserve_patterns=["*.lic"],
        parent_pid=0,
        work_dir=str(app_dir / updater.INTERNAL_WORK_DIR / session_id),
    )
    return session.write(str(log_dir / "session.json"))


def test_create_update_session_writes_metadata(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    zip_path = _make_full_zip(tmp_path / "update.zip", "9.9.9", {"new.txt": "new"})
    log_root = tmp_path / "log-root"

    monkeypatch.setattr(updater, "_get_app_dir", lambda: str(app_dir))
    monkeypatch.setattr(
        updater,
        "_get_main_entry",
        lambda: (str(app_dir / f"{updater.APP_NAME_EN}.exe"), str(tmp_path / "main.py")),
    )
    monkeypatch.setattr(updater, "_get_update_log_root", lambda: str(log_root))

    session_path = updater.create_update_session(
        str(zip_path),
        is_patch=False,
        target_version="9.9.9",
        current_version="1.0.0",
    )

    session = updater.UpdateSession.from_file(session_path)
    assert session.app_dir == str(app_dir)
    assert session.download_zip_path == str(zip_path)
    assert session.target_version == "9.9.9"
    assert session.current_version == "1.0.0"
    assert session.cleanup_targets == [str(zip_path)]
    assert session.work_dir.endswith(session.session_id)


def test_ensure_install_ready_rejects_unwritable_dir(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    zip_path = _make_full_zip(tmp_path / "update.zip", "9.9.9", {"new.txt": "new"})

    monkeypatch.setattr(updater, "is_install_dir_writable", lambda path=None: False)

    with pytest.raises(updater.UpdatePreparationError):
        updater.ensure_install_ready(str(zip_path), is_patch=False, app_dir=str(app_dir))


def test_ensure_install_ready_rejects_low_disk_space(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    zip_path = _make_full_zip(tmp_path / "update.zip", "9.9.9", {"new.txt": "new" * 1024})

    monkeypatch.setattr(updater, "is_install_dir_writable", lambda path=None: True)
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _path: shutil._ntuple_diskusage(total=1024, used=1000, free=24),
    )

    with pytest.raises(updater.UpdatePreparationError):
        updater.ensure_install_ready(str(zip_path), is_patch=False, app_dir=str(app_dir))


def test_ensure_install_ready_reports_validate_steps(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    for index in range(3):
        (app_dir / f"file-{index}.txt").write_text(f"payload-{index}", encoding="utf-8")
    zip_path = _make_full_zip(tmp_path / "update.zip", "9.9.9", {"new.txt": "new" * 1024})
    progress_messages: list[str] = []

    monkeypatch.setattr(updater, "PROGRESS_THROTTLE_SECONDS", 0)
    monkeypatch.setattr(updater, "is_install_dir_writable", lambda path=None: True)
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _path: shutil._ntuple_diskusage(total=1024**4, used=1024, free=1024**4),
    )

    result = updater.ensure_install_ready(
        str(zip_path),
        is_patch=False,
        app_dir=str(app_dir),
        progress_callback=lambda text: progress_messages.append(text),
    )

    assert result["app_dir"] == str(app_dir)
    assert "正在检查写入权限" in progress_messages
    scan_messages = [text for text in progress_messages if text.startswith("正在统计安装目录大小（已扫描 ")]
    assert len(scan_messages) >= 3
    assert scan_messages[-1].endswith("3 个文件）")


def test_run_update_session_rolls_back_full_install_on_failure(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "old.txt").write_text("old-version", encoding="utf-8")
    (app_dir / f"{updater.APP_NAME_EN}.exe").write_text("binary", encoding="utf-8")
    zip_path = _make_full_zip(
        tmp_path / "full-update.zip",
        "9.9.9",
        {
            "old.txt": "new-version",
            "new.txt": "brand-new",
        },
    )
    session_path = _write_session(tmp_path, app_dir=app_dir, zip_path=zip_path, is_patch=False)

    monkeypatch.setattr(updater, "_wait_for_process_exit", lambda pid: None)
    real_copy_tree = updater._copy_tree_contents

    def flaky_copy(src_dir, dst_dir):
        real_copy_tree(src_dir, dst_dir)
        raise RuntimeError("copy failed after overwrite")

    monkeypatch.setattr(updater, "_copy_tree_contents", flaky_copy)

    result = updater.run_update_session(session_path)

    assert result["success"] is False
    assert result["rollback_ok"] is True
    assert (app_dir / "old.txt").read_text(encoding="utf-8") == "old-version"
    assert not (app_dir / "new.txt").exists()


def test_run_update_session_rolls_back_patch_install_on_failure(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "keep.txt").write_text("old-content", encoding="utf-8")
    (app_dir / "obsolete.txt").write_text("remove-me", encoding="utf-8")
    (app_dir / f"{updater.APP_NAME_EN}.exe").write_text("binary", encoding="utf-8")
    allowed_source_hashes = {
        "keep.txt": [updater._sha256_file(str(app_dir / "keep.txt"))],
        "new.txt": [updater.PATCH_MISSING_SENTINEL],
        "obsolete.txt": [updater._sha256_file(str(app_dir / "obsolete.txt"))],
    }
    zip_path = _make_patch_zip(
        tmp_path / "patch-update.zip",
        included_files={
            "keep.txt": "new-content",
            "new.txt": "brand-new",
        },
        deleted=["obsolete.txt"],
        allowed_source_hashes=allowed_source_hashes,
    )
    session_path = _write_session(tmp_path, app_dir=app_dir, zip_path=zip_path, is_patch=True)

    monkeypatch.setattr(updater, "_wait_for_process_exit", lambda pid: None)
    real_apply_patch = updater._apply_patch_update

    def flaky_apply(session, extract_root, patch_manifest):
        real_apply_patch(session, extract_root, patch_manifest)
        raise RuntimeError("patch failed after apply")

    monkeypatch.setattr(updater, "_apply_patch_update", flaky_apply)

    result = updater.run_update_session(session_path)

    assert result["success"] is False
    assert result["rollback_ok"] is True
    assert (app_dir / "keep.txt").read_text(encoding="utf-8") == "old-content"
    assert not (app_dir / "new.txt").exists()
    assert (app_dir / "obsolete.txt").read_text(encoding="utf-8") == "remove-me"


def test_run_update_session_rejects_patch_when_min_version_mismatched(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "keep.txt").write_text("old-content", encoding="utf-8")
    (app_dir / f"{updater.APP_NAME_EN}.exe").write_text("binary", encoding="utf-8")
    zip_path = _make_patch_zip(
        tmp_path / "patch-update.zip",
        included_files={"keep.txt": "new-content"},
        allowed_source_hashes={
            "keep.txt": [updater._sha256_file(str(app_dir / "keep.txt"))],
        },
        min_version="2.0.0",
    )
    session_path = _write_session(tmp_path, app_dir=app_dir, zip_path=zip_path, is_patch=True)

    monkeypatch.setattr(updater, "_wait_for_process_exit", lambda pid: None)

    result = updater.run_update_session(session_path)

    assert result["success"] is False
    assert result["error_code"] == "patch_mismatch"
    assert result["retry_mode"] == updater.RETRY_MODE_FULL_PACKAGE
    assert result["rollback_ok"] is False
    assert (app_dir / "keep.txt").read_text(encoding="utf-8") == "old-content"


def test_run_update_session_rejects_patch_when_file_hash_mismatched(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "keep.txt").write_text("tampered", encoding="utf-8")
    (app_dir / f"{updater.APP_NAME_EN}.exe").write_text("binary", encoding="utf-8")
    zip_path = _make_patch_zip(
        tmp_path / "patch-update.zip",
        included_files={"keep.txt": "new-content", "new.txt": "brand-new"},
        allowed_source_hashes={
            "keep.txt": ["sha256-will-not-match"],
            "new.txt": [updater.PATCH_MISSING_SENTINEL],
        },
    )
    session_path = _write_session(tmp_path, app_dir=app_dir, zip_path=zip_path, is_patch=True)

    monkeypatch.setattr(updater, "_wait_for_process_exit", lambda pid: None)

    result = updater.run_update_session(session_path)

    assert result["success"] is False
    assert result["error_code"] == "patch_mismatch"
    assert result["retry_mode"] == updater.RETRY_MODE_FULL_PACKAGE
    assert not (app_dir / "new.txt").exists()


def test_run_update_session_applies_patch_when_missing_file_is_allowed(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "keep.txt").write_text("old-content", encoding="utf-8")
    (app_dir / f"{updater.APP_NAME_EN}.exe").write_text("binary", encoding="utf-8")
    zip_path = _make_patch_zip(
        tmp_path / "patch-update.zip",
        included_files={"keep.txt": "new-content", "new.txt": "brand-new"},
        allowed_source_hashes={
            "keep.txt": [updater._sha256_file(str(app_dir / "keep.txt"))],
            "new.txt": [updater.PATCH_MISSING_SENTINEL],
        },
    )
    session_path = _write_session(tmp_path, app_dir=app_dir, zip_path=zip_path, is_patch=True)

    monkeypatch.setattr(updater, "_wait_for_process_exit", lambda pid: None)

    result = updater.run_update_session(session_path)

    assert result["success"] is True
    assert (app_dir / "keep.txt").read_text(encoding="utf-8") == "new-content"
    assert (app_dir / "new.txt").read_text(encoding="utf-8") == "brand-new"


def test_run_update_session_reports_patch_validation_progress(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "keep.txt").write_text("old-content", encoding="utf-8")
    (app_dir / f"{updater.APP_NAME_EN}.exe").write_text("binary", encoding="utf-8")
    zip_path = _make_patch_zip(
        tmp_path / "patch-update.zip",
        included_files={
            "keep.txt": "new-content",
            "new.txt": "brand-new",
        },
        allowed_source_hashes={
            "keep.txt": [updater._sha256_file(str(app_dir / "keep.txt"))],
            "new.txt": [updater.PATCH_MISSING_SENTINEL],
        },
    )
    session_path = _write_session(tmp_path, app_dir=app_dir, zip_path=zip_path, is_patch=True)
    stage_events: list[tuple[str, str]] = []

    monkeypatch.setattr(updater, "PROGRESS_THROTTLE_SECONDS", 0)
    monkeypatch.setattr(updater, "_wait_for_process_exit", lambda pid: None)

    result = updater.run_update_session(
        session_path,
        stage_callback=lambda key, text: stage_events.append((key, text)),
    )

    assert result["success"] is True
    validate_messages = [text for key, text in stage_events if key == "validate"]
    assert "校验安装环境" in validate_messages
    assert "正在清理上次失败残留" in validate_messages
    assert "正在检查写入权限" in validate_messages
    assert "正在校验补丁适用性（1/2）" in validate_messages
    assert "正在校验补丁适用性（2/2）" in validate_messages
    assert "正在解压补丁包（1/3）" in validate_messages
    assert "正在解压补丁包（3/3）" in validate_messages


def test_run_update_session_cleans_stale_update_sessions_before_install(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "old.txt").write_text("old-content", encoding="utf-8")
    (app_dir / f"{updater.APP_NAME_EN}.exe").write_text("binary", encoding="utf-8")
    stale_dir = app_dir / updater.INTERNAL_WORK_DIR / "stale-session"
    (stale_dir / "extract").mkdir(parents=True)
    (stale_dir / "extract" / "leftover.txt").write_text("leftover", encoding="utf-8")
    zip_path = _make_full_zip(
        tmp_path / "full-update.zip",
        "9.9.9",
        {
            "old.txt": "new-content",
            "new.txt": "brand-new",
        },
    )
    session_path = _write_session(
        tmp_path,
        app_dir=app_dir,
        zip_path=zip_path,
        is_patch=False,
        session_id="session-keep",
    )
    stage_events: list[tuple[str, str]] = []

    monkeypatch.setattr(updater, "PROGRESS_THROTTLE_SECONDS", 0)
    monkeypatch.setattr(updater, "_wait_for_process_exit", lambda pid: None)

    result = updater.run_update_session(
        session_path,
        stage_callback=lambda key, text: stage_events.append((key, text)),
    )

    assert result["success"] is True
    assert not stale_dir.exists()
    assert ("validate", "正在清理上次失败残留") in stage_events


def test_run_update_session_reports_stale_session_cleanup_failure(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "old.txt").write_text("old-content", encoding="utf-8")
    (app_dir / f"{updater.APP_NAME_EN}.exe").write_text("binary", encoding="utf-8")
    stale_dir = app_dir / updater.INTERNAL_WORK_DIR / "stale-session"
    (stale_dir / "extract").mkdir(parents=True)
    (stale_dir / "extract" / "leftover.txt").write_text("leftover", encoding="utf-8")
    zip_path = _make_full_zip(
        tmp_path / "full-update.zip",
        "9.9.9",
        {
            "old.txt": "new-content",
            "new.txt": "brand-new",
        },
    )
    session_path = _write_session(
        tmp_path,
        app_dir=app_dir,
        zip_path=zip_path,
        is_patch=False,
        session_id="session-keep",
    )
    stage_events: list[tuple[str, str]] = []
    real_rmtree = shutil.rmtree

    monkeypatch.setattr(updater, "_wait_for_process_exit", lambda pid: None)

    def flaky_rmtree(path, *args, **kwargs):
        if Path(path) == stale_dir:
            raise PermissionError("used by another process")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", flaky_rmtree)

    result = updater.run_update_session(
        session_path,
        stage_callback=lambda key, text: stage_events.append((key, text)),
    )

    assert result["success"] is False
    assert result["error_code"] == "stale_session_cleanup_failed"
    assert result["rollback_ok"] is False
    assert "关闭软件" in result["user_message"]
    assert "重启" in result["user_message"]
    assert str(stale_dir) in result["error"]
    assert ("validate", "正在清理上次失败残留") in stage_events


def test_run_update_session_reports_full_package_validate_steps(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "old.txt").write_text("old-content", encoding="utf-8")
    (app_dir / f"{updater.APP_NAME_EN}.exe").write_text("binary", encoding="utf-8")
    stale_dir = app_dir / updater.INTERNAL_WORK_DIR / "stale-session"
    stale_dir.mkdir(parents=True)
    (stale_dir / "leftover.txt").write_text("leftover", encoding="utf-8")
    zip_path = _make_full_zip(
        tmp_path / "full-update.zip",
        "9.9.9",
        {
            "old.txt": "new-content",
            "new.txt": "brand-new",
        },
    )
    session_path = _write_session(
        tmp_path,
        app_dir=app_dir,
        zip_path=zip_path,
        is_patch=False,
        session_id="session-keep",
    )
    stage_events: list[tuple[str, str]] = []

    monkeypatch.setattr(updater, "PROGRESS_THROTTLE_SECONDS", 0)
    monkeypatch.setattr(updater, "_wait_for_process_exit", lambda pid: None)

    result = updater.run_update_session(
        session_path,
        stage_callback=lambda key, text: stage_events.append((key, text)),
    )

    assert result["success"] is True
    validate_messages = [text for key, text in stage_events if key == "validate"]
    expected_messages = [
        "校验安装环境",
        "正在清理上次失败残留",
        "正在检查写入权限",
        "正在统计安装目录大小（已扫描 2 个文件）",
        "正在解压完整安装包（1/2）",
        "正在解压完整安装包（2/2）",
    ]
    for message in expected_messages:
        assert message in validate_messages
    indices = [validate_messages.index(message) for message in expected_messages]
    assert indices == sorted(indices)
