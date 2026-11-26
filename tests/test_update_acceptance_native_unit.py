"""原生验收夹具必须真实改动保存状态并记录需保留的文件。"""
import json
from pathlib import Path
import sys
import hashlib
import zipfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import update_acceptance_native as native


def test_formal_saved_case_fixture_preserves_existing_fields_and_both_data_roots(tmp_path):
    for root in ("data", "_internal/data"):
        cases = tmp_path / root / "siphon_cases"
        cases.mkdir(parents=True)
        (cases / "工况1.siphon.json").write_text(json.dumps({"case_name": "旧工况", "geometry": [1, 2, 3]}), encoding="utf-8")
    (tmp_path / "qa.lic").write_bytes(b"test-authorization")
    (tmp_path / "program.dll").write_bytes(b"program")
    before = native.saved_data(tmp_path)
    assert len(before) == 5 and "qa.lic" in before and "program.dll" not in before
    for root in ("data", "_internal/data"):
        content = json.loads((tmp_path / root / "siphon_cases/工况1.siphon.json").read_text(encoding="utf-8"))
        assert content["geometry"] == [1, 2, 3] and content["case_name"] != "旧工况"
    native.verify_data(tmp_path, before)


def test_online_acceptance_uses_actual_ui_phases_and_success_page_launch(monkeypatch, tmp_path):
    old = tmp_path / "old.zip"
    with zipfile.ZipFile(old, "w") as archive:
        archive.writestr("old/CanalHydraulicCalc.exe", b"old-main")
        archive.writestr("old/CanalHydraulicCalcUpdater.exe", b"old-helper")
    work, logs_root, clicks, launched, closed = tmp_path / "work", tmp_path / "profile", [], [], []
    state = {"frame": 0, "downloaded": False, "confirming": False, "installed": False, "launched": False}
    version_data = {"latest_version": "1.4.7", "download_url": "https://example.test/full.zip",
                    "patch_url": "https://example.test/patch.zip"}
    binding = {"full_zip": "sealed-full-package", "patch_zip": "sealed-package"}
    contents = {"CanalHydraulicCalc.exe": b"new-main", "CanalHydraulicCalcUpdater.exe": b"new-helper"}
    request = {"version": "1.4.7", "version_data": version_data, "manifest_url": "https://example.test/version.json",
               "work_root": str(work), "latest": "1.4.6", "binding": binding, "baselines": {"1.4.6": {}},
               "programs": {path: hashlib.sha256(data).hexdigest() for path, data in contents.items()}}
    class Process:
        pid = 321
        def __init__(self, command, *, cwd):
            launched.append(command)
            assert Path(cwd) == work / "base/old"
        def poll(self):
            return 0 if state["launched"] else None
    class Probe:
        def descendants(self, pid):
            return {pid}
        def pids_in_directories(self, directories):
            return {321, 333}
        def windows(self, pids):
            state["frame"] += 1
            if state["launched"]:
                return [{"hwnd": 3, "pid": 333, "title": "测试主窗口 V1.4.7", "responsive": True}]
            if state["installed"]:
                return [{"hwnd": 2, "pid": 321, "title": "安装更新", "responsive": True}]
            if state["confirming"]:
                return [{"hwnd": 4, "pid": 321, "title": "", "responsive": True}]
            return [{"hwnd": 1, "pid": 321, "title": "检查更新", "responsive": True}]
        def close_directories(self, directories, **kwargs):
            closed.append(kwargs)
            return True
        def close(self, process):
            return True
    def click(hwnd, *, phase):
        if phase == "download":
            state["downloaded"] = True
        elif phase == "install" and state["downloaded"]:
            state["confirming"] = True
        elif phase == "confirm" and state["confirming"]:
            assert hwnd == 4
            state["installed"] = True
            app = work / "base/old"
            for path, content in contents.items():
                (app / path).write_bytes(content)
            logs = logs_root / "logs/qa"
            logs.mkdir(parents=True)
            native.gate.write_json(logs / "session.json", {"app_dir": str(app), "session_id": "qa", "log_dir": str(logs),
                "target_version": "1.4.7", "expected_package_sha256": "sealed-package", "is_patch": True})
            (logs / "install.log").write_text("安装完成", encoding="utf-8")
        elif phase == "launch" and state["installed"]:
            state["launched"] = True
        else:
            return False
        clicks.append(phase)
        return True
    monkeypatch.setattr(native.gate, "read_json_url", lambda *_: version_data)
    monkeypatch.setattr(native, "baseline_package", lambda *_: old)
    monkeypatch.setattr(native.updater, "_get_update_log_root", lambda: str(logs_root))
    monkeypatch.setattr(native.subprocess, "Popen", Process)
    monkeypatch.setattr(native, "invoke_button", click)
    monkeypatch.setattr(native.time, "sleep", lambda _: None)
    report = {"cases": {}}
    native.online_acceptance(request, report, Probe())
    assert clicks == ["download", "install", "confirm", "launch"]
    assert len(launched) == 1 and launched[0][-1] == "--show-update-dialog"
    evidence = report["cases"]["U09"]["evidence"]
    assert evidence["main"]["launch_button_used"] and evidence["main"]["main_window_samples"] >= 4
    assert closed[0]["required_pids"] == {333}
    assert all(item["before_sha256"] == item["after_sha256"] for item in evidence["user_data_hashes"].values())
