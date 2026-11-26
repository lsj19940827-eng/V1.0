"""发布门槛的故障注入测试，所有发布 API 和 Git 写操作均使用替身。"""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import release, release_acceptance as acceptance


def sha(data):
    return hashlib.sha256(data).hexdigest()


def candidate(tmp_path, *, runtime=False, patch=False):
    files = {"CanalHydraulicCalc.exe": b"main", "CanalHydraulicCalcUpdater.exe": b"helper", "program.txt": b"program"}
    if runtime:
        files["_internal/data/siphon_cases/工况1.siphon.json"] = b"user case"
    full = tmp_path / "full.zip"
    with zipfile.ZipFile(full, "w") as archive:
        for name, data in files.items():
            archive.writestr("CanalHydraulicCalc-V1.4.7/" + name, data)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": "1.4.7", "files": {p: sha(data) for p, data in files.items()}}), encoding="utf-8")
    assets = {"full_zip": str(full), "manifest_path": str(manifest), "full_size_mb": full.stat().st_size / (1024*1024)}
    if patch:
        path = tmp_path / "patch.zip"
        meta = {"type": "universal_patch", "version": "1.4.7", "min_version": "1.4.6", "source_versions": ["1.4.6"],
                "included_files": ["program.txt"], "deleted": [], "target_files": {p: sha(data) for p, data in files.items()},
                "allowed_source_hashes": {"program.txt": [sha(b"old-program")]}}
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("patch_manifest.json", json.dumps(meta))
            archive.writestr("program.txt", files["program.txt"])
        assets.update(patch_zip=str(path), patch_min_version="1.4.6", patch_size_mb=round(path.stat().st_size / (1024*1024), 2),
                      patch_source_versions=["1.4.6"], patch_changed_count=1, patch_deleted_count=0)
    return assets


def make_gate(tmp_path, assets):
    binding, *_ = acceptance.inspect_candidate("1.4.7", assets)
    return acceptance.ReleaseAcceptance("1.4.7", assets, binding, tmp_path, {}, "1.4.6", [], {"status": "local_passed"})


def test_actual_candidate_contains_expected_program_bytes(tmp_path):
    assets = candidate(tmp_path, patch=True)
    binding, prefix, programs, metadata = acceptance.inspect_candidate("1.4.7", assets)
    assert binding["main_exe"] == sha(b"main")
    assert binding["helper_exe"] == sha(b"helper")
    assert binding["patch_zip"] == acceptance.release_snapshot.sha256_file(assets["patch_zip"])
    assert programs == metadata["target_files"]
    assert prefix == "CanalHydraulicCalc-V1.4.7/"


@pytest.mark.parametrize("key,bad", [("patch_min_version", "1.3.0"), ("patch_source_versions", []),
                                     ("patch_changed_count", 0), ("patch_deleted_count", 1)])
def test_patch_info_cannot_publish_a_different_range_or_policy(tmp_path, key, bad):
    assets = candidate(tmp_path, patch=True)
    assets[key] = bad
    with pytest.raises(acceptance.AcceptanceError, match="发布字段"):
        acceptance.inspect_candidate("1.4.7", assets)


def test_real_runtime_case_is_rejected_before_any_publish_action(tmp_path):
    with pytest.raises(acceptance.AcceptanceError, match="用户数据"):
        acceptance.inspect_candidate("1.4.7", candidate(tmp_path, runtime=True))


def test_manifest_cannot_attest_different_program_bytes(tmp_path):
    assets = candidate(tmp_path)
    data = json.loads(Path(assets["manifest_path"]).read_text())
    data["files"]["program.txt"] = "0" * 64
    Path(assets["manifest_path"]).write_text(json.dumps(data))
    with pytest.raises(acceptance.AcceptanceError, match="manifest 不一致"):
        acceptance.inspect_candidate("1.4.7", assets)


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:/escape.txt", "dir\\escape.txt",
                                  "program.dll.", "dir//program.dll", "dir/./program.dll", "con.dll"])
def test_unsafe_zip_cannot_enter_native_extraction(tmp_path, name):
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        # Windows 的 ZipInfo 构造会规范化反斜杠；保留原始中央目录字节以验证拒绝路径。
        info = zipfile.ZipInfo(name)
        info.filename = name
        archive.writestr(info, b"bad")
    with zipfile.ZipFile(path) as archive, pytest.raises(acceptance.AcceptanceError, match="不安全"):
        acceptance.checked_members(archive)


def test_windows_case_collision_is_rejected(tmp_path):
    path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Program.dll", b"one")
        archive.writestr("program.dll", b"two")
    with zipfile.ZipFile(path) as archive, pytest.raises(acceptance.AcceptanceError, match="重复"):
        acceptance.checked_members(archive)


def test_sealed_package_cannot_change_after_acceptance(tmp_path):
    assets = candidate(tmp_path)
    gate = make_gate(tmp_path, assets)
    with zipfile.ZipFile(assets["full_zip"], "a") as archive:
        archive.writestr("CanalHydraulicCalc-V1.4.7/new-file", b"unreviewed")
    with pytest.raises(acceptance.AcceptanceError):
        gate.assert_unchanged()


def test_declared_baseline_requires_its_formal_snapshot(tmp_path):
    with pytest.raises(acceptance.AcceptanceError, match="快照"):
        acceptance.load_baselines("1.4.7", {"source_versions": ["1.4.6"]}, tmp_path)


def test_baseline_source_hash_mismatch_blocks_the_claimed_version(tmp_path):
    root = tmp_path / "snapshots/v1.4.6"
    root.mkdir(parents=True)
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"version": "1.4.6", "files": {"program.txt": sha(b"real-old")}}))
    (root / "snapshot.json").write_text(json.dumps({"version": "1.4.6", "manifest": {"path": str(manifest)}}))
    metadata = {"source_versions": ["1.4.6"], "allowed_source_hashes": {"program.txt": [sha(b"another-old")]}}
    with pytest.raises(acceptance.AcceptanceError, match="不适用于"):
        acceptance.load_baselines("1.4.7", metadata, tmp_path / "snapshots")


class Response(io.BytesIO):
    def __init__(self, content, content_type="application/zip", status=200):
        super().__init__(content)
        self.headers = {"Content-Type": content_type}
        self.status = status


@pytest.mark.parametrize("content_type,status,body", [
    ("text/html", 200, b"<html>ok</html>"), ("application/zip", 206, b"part"),
    ("application/zip", 200, b"corrupt"), ("application/zip", 200, b"file-too-large"),
])
def test_http_success_does_not_bypass_complete_download_verification(content_type, status, body):
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.verify_download("https://example.test/full.zip", sha(b"good"), 4,
                                   opener=lambda *_args, **_kwargs: Response(body, content_type, status))


def test_complete_download_verifies_actual_bytes():
    receipt = acceptance.verify_download("https://example.test/full.zip", sha(b"good"), 4,
                                          opener=lambda *_args, **_kwargs: Response(b"good"))
    assert receipt["method"] == "complete_download"
    assert receipt["sha256"] == sha(b"good")


def test_remote_failure_does_not_produce_switch_receipt(tmp_path, monkeypatch):
    assets = candidate(tmp_path)
    gate = make_gate(tmp_path, assets)
    data = release._build_version_data("1.4.7", {"download_url": "https://example.test/full.zip"}, assets, "说明")
    monkeypatch.setattr(acceptance, "verify_download", lambda *_: (_ for _ in ()).throw(acceptance.AcceptanceError("错误包")))
    with pytest.raises(acceptance.AcceptanceError, match="U08"):
        acceptance.verify_remote(gate, data)
    assert gate.local_report["remote"]["status"] == "failed"
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.require_remote_receipt(gate, data)


def test_gist_function_cannot_be_called_without_acceptance(tmp_path, monkeypatch):
    assets = candidate(tmp_path)
    writes = []
    monkeypatch.setattr(release, "_github_api", lambda *args, **kwargs: writes.append(args))
    with pytest.raises(acceptance.AcceptanceError, match="缺少"):
        release.step_update_gist("1.4.7", {"download_url": "https://example.test/full.zip"}, assets,
                                 "unused-token", "说明", "test-gist")
    assert writes == []


def test_verified_remote_receipt_cannot_be_reused_for_different_urls(tmp_path):
    assets = candidate(tmp_path)
    gate = make_gate(tmp_path, assets)
    gate.local_report["remote"] = {"status": "passed", "binding": gate.binding, "version_data": {"download_url": "one"}}
    with pytest.raises(acceptance.AcceptanceError, match="禁止"):
        acceptance.require_remote_receipt(gate, {"download_url": "another"})


def test_every_declared_direct_proxy_and_mirror_url_is_fully_verified(tmp_path, monkeypatch):
    assets = candidate(tmp_path, patch=True)
    gate = make_gate(tmp_path, assets)
    urls = {"download_url": "https://example.test/full.zip", "download_url_proxy": "https://proxy.test/full.zip",
            "download_url_mirrors": ["https://mirror.test/full.zip"], "patch_url": "https://example.test/patch.zip",
            "patch_url_mirrors": ["https://mirror.test/patch.zip"]}
    data = release._build_version_data("1.4.7", urls, assets, "说明")
    verified = []
    def verify(url, digest, size):
        verified.append((url, digest, size))
        return {"url": url, "sha256": digest, "size_bytes": size}
    monkeypatch.setattr(acceptance, "verify_download", verify)
    receipt = acceptance.verify_remote(gate, data)
    assert {entry[0] for entry in verified} == {urls["download_url"], urls["download_url_proxy"],
        *urls["download_url_mirrors"], urls["patch_url"], *urls["patch_url_mirrors"]}
    assert receipt["status"] == "passed"


def native_report(binding):
    cases = {key: {"status": "passed", "evidence": {"native": True}} for key in acceptance.LOCAL_CASES}
    cases["U02"]["evidence"] = [{
        "source": "1.4.6",
        "saved_case": {"path": "data/siphon_cases/case.json", "before_sha256": "old-case",
                       "saved_sha256": "saved-case", "normal_exit": True},
        "user_data_hashes": {
            "data/siphon_cases/case.json": {"before_sha256": "saved-case", "after_sha256": "saved-case"},
            "license.lic": {"before_sha256": "license", "after_sha256": "license"},
        },
    }]
    cases["U04"]["evidence"] = {"download_seconds": 65, "heartbeat_count": 125, "max_heartbeat_gap_ms": 510,
        "all_ui_callbacks_on_gui_thread": True, "worker_on_background_thread": True, "max_log_blocks": 200,
        "window_observations": 125, "unresponsive_observations": 0, "fallback_exercised": True,
        "speed_visible": True, "result": {"success": True},
        "full_zip_sha256": binding["full_zip"], "main": {"normal_exit": True}}
    return {"binding": binding, "cases": cases}


@pytest.mark.parametrize("bad", [{"download_seconds": 59}, {"max_heartbeat_gap_ms": 2001},
    {"heartbeat_count": 90}, {"worker_on_background_thread": False}, {"max_log_blocks": 301},
    {"unresponsive_observations": 1}, {"result": {"success": False}}, {"speed_visible": False}])
def test_native_metrics_cannot_mark_a_short_or_frozen_run_as_passed(tmp_path, monkeypatch, bad):
    binding = {"helper_exe": "actual-helper", "full_zip": "candidate-zip"}
    report = native_report(binding)
    report["cases"]["U04"]["evidence"].update(bad)
    def run(command, **kwargs):
        acceptance.write_json(command[-1], report)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(acceptance.subprocess, "run", run)
    with pytest.raises(acceptance.AcceptanceError, match="慢速"):
        acceptance.run_native(["unused-runner"], {"mode": "local", "binding": binding,
                         "baselines": {"1.4.6": {}}}, tmp_path)


@pytest.mark.parametrize("kind", ["stale_report", "wrong_binary", "missing_case", "nonzero"])
def test_native_runner_requires_fresh_complete_evidence_from_this_binary(tmp_path, monkeypatch, kind):
    binding = {"helper_exe": "actual-helper", "full_zip": "candidate-zip"}
    report = native_report(binding)
    acceptance.write_json(tmp_path / "native.json", report)
    if kind == "wrong_binary":
        report["binding"] = {"helper_exe": "another-helper"}
    if kind == "missing_case":
        report["cases"].pop("U06")
    def run(command, **kwargs):
        if kind != "stale_report":
            acceptance.write_json(command[-1], report)
        return SimpleNamespace(returncode=1 if kind == "nonzero" else 0)
    monkeypatch.setattr(acceptance.subprocess, "run", run)
    with pytest.raises(acceptance.AcceptanceError):
        acceptance.run_native(["unused-runner"], {"mode": "local", "binding": binding}, tmp_path)


@pytest.mark.parametrize("bad", [{"main_window_samples": 1}, {"normal_exit": False}, {"launch_button_used": False}])
def test_online_receipt_requires_launch_button_and_normal_exit(tmp_path, monkeypatch, bad):
    binding = {"full_zip": "sealed-package"}
    evidence = {"source": "1.4.6", "unresponsive_observations": 0,
                "main": {"main_window_samples": 4, "normal_exit": True, "launch_button_used": True}}
    evidence["main"].update(bad)
    def run(command, **kwargs):
        acceptance.write_json(command[-1], {"binding": binding, "cases": {"U09": {"status": "passed", "evidence": evidence}}})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(acceptance.subprocess, "run", run)
    with pytest.raises(acceptance.AcceptanceError, match="成功页启动"):
        acceptance.run_native(["unused-runner"], {"mode": "online", "binding": binding, "latest": "1.4.6"}, tmp_path)


def mocked_release(tmp_path, monkeypatch):
    assets = candidate(tmp_path)
    gate = make_gate(tmp_path, assets)
    calls = []
    old = {"latest_version": "1.4.6", "download_url": "https://example.test/old.zip"}
    state = {"manifest": copy.deepcopy(old)}
    monkeypatch.setattr(release, "_get_token", lambda: "test-token")
    monkeypatch.setattr(release, "_get_gitee_token", lambda: "test-token")
    monkeypatch.setattr(release, "_github_api", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(release, "_gitee_api", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(release, "_current_branch", lambda: "master")
    monkeypatch.setattr(release, "step_get_current_version", lambda: "1.4.7")
    monkeypatch.setattr(release, "step_build", lambda: calls.append("build") or assets)
    monkeypatch.setattr(release, "load_gist_version", lambda *_: copy.deepcopy(state["manifest"]))
    monkeypatch.setattr(acceptance, "read_json_url", lambda *_args, **_kwargs: copy.deepcopy(state["manifest"]))
    def save(_token, data, *_args):
        calls.append("gist:" + data["latest_version"])
        state["manifest"] = copy.deepcopy(data)
    monkeypatch.setattr(release, "save_gist_version", save)
    monkeypatch.setattr(acceptance, "prepare_local", lambda *_args, **_kwargs: calls.append("local") or gate)
    monkeypatch.setattr(release, "step_git_commit_and_tag", lambda *_: calls.append("git"))
    monkeypatch.setattr(release, "step_create_release", lambda *_: calls.append("release") or {})
    monkeypatch.setattr(release, "step_upload_assets", lambda *_: calls.append("upload") or {"download_url": "https://example.test/full.zip"})
    monkeypatch.setattr(release, "step_create_gitee_release_and_upload_assets", lambda *_args, **_kwargs: {})
    def remote(g, data):
        calls.append("remote")
        g.local_report["remote"] = {"status": "passed", "binding": g.binding, "version_data": data}
    monkeypatch.setattr(acceptance, "verify_remote", remote)
    monkeypatch.setattr(acceptance, "verify_online", lambda *_: calls.append("online"))
    monkeypatch.setattr(release.release_snapshot, "write_release_snapshot", lambda **_: calls.append("snapshot") or "test-snapshot")
    return calls, state, old, gate


def test_successful_release_orders_all_gates_before_mutations(tmp_path, monkeypatch):
    calls, state, old, gate = mocked_release(tmp_path, monkeypatch)
    release.release("patch", no_bump=True)
    assert calls == ["build", "local", "git", "release", "upload", "remote", "gist:1.4.7", "online", "snapshot"]
    assert state["manifest"]["latest_version"] == "1.4.7"
    assert gate.local_report["status"] == "passed"


@pytest.mark.parametrize("stage", ["local", "remote"])
def test_failed_gate_blocks_every_later_publish_stage(tmp_path, monkeypatch, stage):
    calls, state, old, gate = mocked_release(tmp_path, monkeypatch)
    def fail(*_args, **_kwargs):
        calls.append(stage)
        raise acceptance.AcceptanceError("故障注入")
    monkeypatch.setattr(acceptance, "prepare_local" if stage == "local" else "verify_remote", fail)
    with pytest.raises(acceptance.AcceptanceError):
        release.release("patch", no_bump=True)
    assert "gist:1.4.7" not in calls and "online" not in calls and "snapshot" not in calls
    if stage == "local":
        assert "git" not in calls and "release" not in calls and "upload" not in calls
    assert state["manifest"] == old


def test_post_switch_online_failure_restores_old_manifest_and_stops(tmp_path, monkeypatch):
    calls, state, old, gate = mocked_release(tmp_path, monkeypatch)
    monkeypatch.setattr(acceptance, "verify_online", lambda *_: (_ for _ in ()).throw(acceptance.AcceptanceError("线上失败")))
    with pytest.raises(acceptance.AcceptanceError, match="restored_previous_manifest"):
        release.release("patch", no_bump=True)
    assert state["manifest"] == old
    assert calls[-1] == "gist:1.4.6" and "snapshot" not in calls


def test_failed_gist_response_after_write_also_restores_old_manifest(tmp_path, monkeypatch):
    calls, state, old, gate = mocked_release(tmp_path, monkeypatch)
    original = release.save_gist_version
    def uncertain(token, data, *_args):
        original(token, data)
        if data["latest_version"] == "1.4.7":
            raise OSError("写入后响应丢失")
    monkeypatch.setattr(release, "save_gist_version", uncertain)
    with pytest.raises(acceptance.AcceptanceError, match="restored_previous_manifest"):
        release.release("patch", no_bump=True)
    assert state["manifest"] == old and "online" not in calls and "snapshot" not in calls


def test_concurrent_manifest_change_is_never_overwritten_on_failure(tmp_path, monkeypatch):
    calls, state, old, gate = mocked_release(tmp_path, monkeypatch)
    third_party = {"latest_version": "1.5.0", "download_url": "https://example.test/other.zip"}
    def remote(g, data):
        g.local_report["remote"] = {"status": "passed", "binding": g.binding, "version_data": data}
        state["manifest"] = third_party
    monkeypatch.setattr(acceptance, "verify_remote", remote)
    with pytest.raises(acceptance.AcceptanceError, match="conflict"):
        release.release("patch", no_bump=True)
    assert state["manifest"] == third_party
    assert not any(call.startswith("gist:") for call in calls)


def test_restore_failure_is_reported_and_never_claimed_success(tmp_path, monkeypatch):
    calls, state, old, gate = mocked_release(tmp_path, monkeypatch)
    save = release.save_gist_version
    def fail_restore(token, data, *_args):
        if data == old:
            raise OSError("故障注入：恢复失败")
        return save(token, data)
    monkeypatch.setattr(release, "save_gist_version", fail_restore)
    monkeypatch.setattr(acceptance, "verify_online", lambda *_: (_ for _ in ()).throw(acceptance.AcceptanceError("线上失败")))
    with pytest.raises(acceptance.AcceptanceError, match="恢复结果：failed"):
        release.release("patch", no_bump=True)
    assert gate.local_report["status"] == "failed"
    assert "snapshot" not in calls


def test_post_acceptance_snapshot_failure_also_restores_previous_manifest(tmp_path, monkeypatch):
    calls, state, old, gate = mocked_release(tmp_path, monkeypatch)
    monkeypatch.setattr(release.release_snapshot, "write_release_snapshot",
                        lambda **_: (_ for _ in ()).throw(OSError("故障注入：快照写入失败")))
    with pytest.raises(acceptance.AcceptanceError, match="restored_previous_manifest"):
        release.release("patch", no_bump=True)
    assert state["manifest"] == old and gate.local_report["status"] == "failed"


def test_verify_only_never_loads_tokens_builds_or_publishes(tmp_path, monkeypatch):
    assets = candidate(tmp_path)
    gate = make_gate(tmp_path, assets)
    monkeypatch.setattr(release, "collect_assets", lambda *_: assets)
    monkeypatch.setattr(acceptance, "prepare_local", lambda *_args, **_kwargs: gate)
    for name in ("_get_token", "_get_gitee_token", "step_build", "step_bump_version", "release"):
        monkeypatch.setattr(release, name, lambda *_args, **_kwargs: pytest.fail("只验收触发了发布或版本变更"))
    assert release.main(["--verify-only", "--version", "1.4.7", "--assets-dir", str(tmp_path)]) == 0


def test_verify_only_failure_is_nonzero(tmp_path, monkeypatch):
    assets = candidate(tmp_path, runtime=True)
    monkeypatch.setattr(release, "collect_assets", lambda *_: assets)
    assert release.main(["--verify-only", "--version", "1.4.7", "--assets-dir", str(tmp_path)]) == 2
