# -*- coding: utf-8 -*-
"""在隔离目录中运行正式 EXE；只由发布验收调用，不执行任何发布写操作。"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import updater
from tools import release_acceptance as gate


class WindowsProbe:
    def __init__(self):
        gate.require(os.name == "nt", "正式 EXE 原生验收必须在 Windows 上执行")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = [self.callback, wintypes.LPARAM]
        self.user.EnumWindows.restype = wintypes.BOOL
        self.user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
            wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        self.user.SendMessageTimeoutW.restype = wintypes.LPARAM
        self.user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.process_names = {}

    def descendants(self, pid):
        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t), ("module", wintypes.DWORD),
                ("threads", wintypes.DWORD), ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                ("flags", wintypes.DWORD), ("name", wintypes.WCHAR * 260)]
        self.kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        self.kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        handle = self.kernel.CreateToolhelp32Snapshot(2, 0)
        parents, entry = {}, Entry()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            found = self.kernel.Process32FirstW(handle, ctypes.byref(entry))
            while found:
                parents[entry.pid] = entry.parent
                self.process_names[entry.pid] = entry.name
                found = self.kernel.Process32NextW(handle, ctypes.byref(entry))
        finally:
            self.kernel.CloseHandle(handle)
        pids = {pid}
        while True:
            added = {child for child, parent in parents.items() if parent in pids}
            if added.issubset(pids):
                return pids
            pids.update(added)

    def pids_in_directories(self, directories):
        result = set()
        prefixes = [str(Path(d).resolve()).casefold() + os.sep for d in directories]
        for pid, name in self.process_names.items():
            if name not in {"CanalHydraulicCalc.exe", "CanalHydraulicCalcUpdater.exe"}:
                continue
            handle = self.kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                continue
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                length = wintypes.DWORD(len(buffer))
                if self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                    if any(buffer.value.casefold().startswith(prefix) for prefix in prefixes):
                        result.add(pid)
            finally:
                self.kernel.CloseHandle(handle)
        return result

    def windows(self, pids):
        result = []
        @self.callback
        def collect(hwnd, _):
            pid = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids and self.user.IsWindowVisible(hwnd):
                title = ctypes.create_unicode_buffer(512)
                self.user.GetWindowTextW(hwnd, title, 512)
                reply = ctypes.c_size_t()
                responsive = bool(self.user.SendMessageTimeoutW(hwnd, 0, 0, 0, 2, 1000, ctypes.byref(reply)))
                result.append({"hwnd": int(hwnd), "pid": pid.value, "title": title.value,
                               "responsive": responsive})
            return True
        self.user.EnumWindows(collect, 0)
        return result

    def close(self, process, *, timeout=15):
        pids = self.descendants(process.pid)
        for window in self.windows(pids):
            self.user.PostMessageW(window["hwnd"], 0x0010, 0, 0)
        try:
            process.wait(timeout=timeout)
            return process.returncode == 0
        except subprocess.TimeoutExpired:
            # 只结束本轮自己创建的进程树，强制清理不计为正常关闭通过。
            for pid in self.descendants(process.pid):
                handle = self.kernel.OpenProcess(1, False, pid)
                if handle:
                    self.kernel.TerminateProcess(handle, 1)
                    self.kernel.CloseHandle(handle)
            process.wait(timeout=10)
            return False

    def close_directories(self, directories, *, timeout=15, required_pids=()):
        """收回隔离目录中已脱离父进程的助手，不能影响用户正在运行的其它实例。"""
        self.descendants(0)
        pids = self.pids_in_directories(directories)
        if not set(required_pids).issubset(pids):
            return False
        for window in self.windows(pids):
            self.user.PostMessageW(window["hwnd"], 0x0010, 0, 0)
        end, normal = time.monotonic() + timeout, True
        for pid in pids:
            handle = self.kernel.OpenProcess(0x101001, False, pid)
            if not handle:
                continue
            try:
                remaining = int(max(0, end-time.monotonic()) * 1000)
                if self.kernel.WaitForSingleObject(handle, remaining) != 0:
                    self.kernel.TerminateProcess(handle, 1)
                    normal = False
                else:
                    code = wintypes.DWORD()
                    normal &= bool(self.kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 0
            finally:
                self.kernel.CloseHandle(handle)
        return normal


def extract_package(package, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(package) as archive:
        gate.checked_members(archive)
        archive.extractall(directory)
    roots = list(directory.rglob("CanalHydraulicCalc.exe"))
    gate.require(len(roots) == 1, "正式包应用目录不明确")
    return roots[0].parent


def saved_data(app):
    """模拟正常保存后的文件状态，同时保留原文件字段和已有用户文件。"""
    for root in ("data", "_internal/data"):
        cases = app / root / "siphon_cases"
        cases.mkdir(parents=True, exist_ok=True)
        existing = list(cases.glob("*.json"))
        path = existing[0] if existing else cases / "验收工况.siphon.json"
        try:
            content = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (ValueError, UnicodeError):
            raise gate.AcceptanceError("正式旧版工况文件不能正常读取")
        gate.require(isinstance(content, dict), "正式旧版工况格式不符合验收样本")
        content["case_name"] = "正常保存后的更新验收工况"
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        autosave = app / root / "autosave" / "qa" / "fixture.txt"
        autosave.parent.mkdir(parents=True, exist_ok=True)
        autosave.write_text("保留自动保存资料", encoding="utf-8")
    return preserved_data(app)


def preserved_data(app):
    return {path.relative_to(app).as_posix(): path.read_bytes()
            for path in app.rglob("*") if path.is_file()
            and gate.should_preserve_path(str(path.relative_to(app)))}


def isolate_profile(directory):
    source = Path(os.environ["APPDATA"]) / "CanalHydCalc"
    override = os.environ.get("CANAL_RELEASE_ACCEPTANCE_LICENSE_FILE")
    license_file = Path(override) if override else source / "license.lic"
    appdata = Path(directory) / "roaming"
    license_dir = appdata / "CanalHydCalc"
    license_dir.mkdir(parents=True, exist_ok=False)
    gate.require(license_file.is_file(), "正式旧版原生验收需要本机有效授权")
    shutil.copy2(license_file, license_dir / "license.lic")
    if (source / ".lc").is_file():
        shutil.copy2(source / ".lc", license_dir / ".lc")
    os.environ["APPDATA"] = str(appdata)
    os.environ["LOCALAPPDATA"] = str(Path(directory) / "local")


def seed_license(app):
    shutil.copy2(Path(os.environ["APPDATA"]) / "CanalHydCalc/license.lic", app / "license.lic")


def verify_data(app, before):
    gate.require(before and all((app / path).is_file() and (app / path).read_bytes() == content
                               for path, content in before.items()), "安装修改或删除了用户数据")
    return {path: {"before_sha256": hashlib.sha256(content).hexdigest(),
                   "after_sha256": updater._sha256_file(str(app / path))} for path, content in before.items()}


def verify_programs(app, programs):
    for path, expected in programs.items():
        actual = app / path
        gate.require(actual.is_file() and updater._sha256_file(str(actual)) == expected,
                     f"安装后的程序目标不一致：{path}")


def baseline_package(snapshot, cache):
    from tools import backfill_patch_release
    entry = snapshot.get("full_zip", {})
    gate.require(entry.get("sha256"), "正式旧版包缺少可信 SHA256")
    return backfill_patch_release._ensure_snapshot_file(entry, str(cache))


def run_installer(probe, helper, app, package, *, version, current, output, is_patch,
                  qa=False, full_url="", full_sha="", expected_sha=None, timeout=240):
    output.mkdir(parents=True)
    runner = output / "CanalHydraulicCalcUpdater.exe"
    shutil.copy2(helper, runner)
    telemetry = output / "helper.json"
    session = updater.UpdateSession(
        session_id="acceptance-" + str(time.time_ns()), app_dir=str(app),
        main_exe_path=str(app / "CanalHydraulicCalc.exe"), download_zip_path=str(package),
        is_patch=is_patch, target_version=version, current_version=current, log_dir=str(output / "logs"),
        cleanup_targets=[], preserve_patterns=(list(updater.DEFAULT_PRESERVE_PATTERNS) if qa else
            [p for p in updater.DEFAULT_PRESERVE_PATTERNS if "siphon_cases" not in p]),
        expected_package_sha256=expected_sha or updater._sha256_file(str(package)),
        full_download_url=full_url, full_package_sha256=full_sha,
    )
    payload = session.to_payload()
    if not qa:
        # Send each historical helper the session schema its own client generated.
        source_version = gate.patch_builder._version_key(current)
        introduced_fields = {
            "1.3.1": ("expected_package_sha256",),
            "1.3.5": ("full_download_url", "full_package_sha256", "full_package_size_mb"),
            "1.3.8": ("full_download_urls",),
        }
        for introduced_version, fields in introduced_fields.items():
            if source_version < gate.patch_builder._version_key(introduced_version):
                for field in fields:
                    payload.pop(field, None)
    path = str(output / "session.json")
    gate.write_json(path, payload)
    command = [str(runner), "--run-session", path]
    if qa:
        command += ["--acceptance-report", str(telemetry)]
    process = subprocess.Popen(command, cwd=output)
    observations, log_text, completed = [], "", False
    begin = time.monotonic()
    try:
        while time.monotonic() - begin < timeout:
            observations.extend(probe.windows(probe.descendants(process.pid)))
            logs = list((output / "logs").glob("*.log"))
            log_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in logs)
            if qa:
                if telemetry.exists() and process.poll() is not None:
                    completed = True
                    break
            elif "安装完成" in log_text:
                completed = True
                break
            elif process.poll() is not None:
                break
            time.sleep(0.1)
        normal_exit = probe.close(process) if process.poll() is None else process.returncode == 0
    finally:
        if process.poll() is None:
            probe.close(process)
    result = {"completed": completed, "normal_exit": normal_exit,
              "package_sha256": session.expected_package_sha256,
              "window_observations": len(observations),
              "unresponsive_observations": sum(not o["responsive"] for o in observations),
              "fallback_exercised": "正在改用完整安装包" in log_text,
              "log_directory": str(output / "logs")}
    gate.require(completed and normal_exit and observations and result["unresponsive_observations"] == 0,
                 "更新助手未完成、无法正常关闭或窗口失去响应")
    if qa:
        measured = json.loads(telemetry.read_text(encoding="utf-8"))
        gate.require(measured.get("helper_sha256") == updater._sha256_file(str(helper)),
                     "助手测量结果与实际构建助手不一致")
        result.update(measured)
    else:
        result["result"] = {"success": "安装完成" in log_text}
    return result


def start_main(probe, app, version):
    process = subprocess.Popen([str(app / "CanalHydraulicCalc.exe")], cwd=app)
    begin, samples = time.monotonic(), []
    try:
        while time.monotonic() - begin < 45 and process.poll() is None:
            windows = probe.windows(probe.descendants(process.pid))
            main = [w for w in windows if f"V{version}" in w["title"]]
            if main:
                samples.extend(main)
                if len(samples) >= 4:
                    break
            time.sleep(0.5)
        normal_exit = probe.close(process)
        gate.require(len(samples) >= 4 and all(w["responsive"] for w in samples) and normal_exit,
                     "新版真实主窗口启动、响应或正常关闭验收失败")
        return {"main_window_samples": len(samples), "normal_exit": normal_exit}
    finally:
        if process.poll() is None:
            probe.close(process)


class PackageServer:
    def __init__(self, payload, *, slow_seconds=0):
        self.payload = payload
        self.slow_seconds = slow_seconds
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_HEAD(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html" if self.path.startswith("/html") else "application/zip")
                self.send_header("Content-Length", str(len(owner.payload)))
                # 不声明 Range，确保限速测试时不会多线程绕过总时长。
                self.end_headers()
            def do_GET(self):
                self.do_HEAD()
                try:
                    if self.path.startswith("/html"):
                        self.wfile.write(b"<html>proxy landing page</html>")
                        return
                    chunk_size = 256 * 1024
                    chunks = max(1, (len(owner.payload) + chunk_size - 1) // chunk_size)
                    for index in range(chunks):
                        self.wfile.write(owner.payload[index * chunk_size:(index + 1) * chunk_size])
                        self.wfile.flush()
                        if owner.slow_seconds:
                            time.sleep(owner.slow_seconds / chunks)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
    def __enter__(self):
        self.thread.start()
        return self
    def url(self, path="full.zip"):
        return f"http://127.0.0.1:{self.server.server_port}/{path}"
    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def synthetic_install(root, version):
    app = root / "app"
    app.mkdir(parents=True)
    (app / "CanalHydraulicCalc.exe").write_bytes(b"old-main")
    (app / "program.txt").write_bytes(b"old-program")
    (app / "qa-preserve.lic").write_bytes(b"test-authorization-file")
    before = saved_data(app)
    full = root / "full.zip"
    with zipfile.ZipFile(full, "w", zipfile.ZIP_STORED) as archive:
        prefix = f"CanalHydraulicCalc-V{version}/"
        archive.writestr(prefix + "CanalHydraulicCalc.exe", b"new-main")
        archive.writestr(prefix + "program.txt", b"new-program")
        archive.writestr(prefix + "payload.bin", os.urandom(4 * 1024 * 1024))
    patch = root / "patch.zip"
    metadata = {"type": "universal_patch", "version": version, "min_version": "1.0.0",
        "included_files": ["program.txt"], "deleted": [],
        "allowed_source_hashes": {"program.txt": [hashlib.sha256(b"different-program").hexdigest()]},
        "target_files": {"program.txt": hashlib.sha256(b"new-program").hexdigest()}}
    with zipfile.ZipFile(patch, "w") as archive:
        archive.writestr("patch_manifest.json", json.dumps(metadata))
        archive.writestr("program.txt", b"new-program")
    return app, before, full, patch


def local_acceptance(request, report, probe):
    from tools.update_acceptance_saved_data import save_formal_case

    work = Path(request["work_root"])
    work.mkdir(parents=True, exist_ok=False)
    cache = work / "cache"
    cache.mkdir()
    candidate = extract_package(request["assets"]["full_zip"], work / "candidate")
    helper = candidate / "CanalHydraulicCalcUpdater.exe"
    cases = report["cases"]
    installs = []
    for source, snapshot in request["baselines"].items():
        app = extract_package(baseline_package(snapshot, cache), work / ("base-" + source))
        _, source_programs = gate.zip_programs(baseline_package(snapshot, cache), allow_runtime=True)
        source_manifest = json.loads(Path(snapshot["manifest"]["path"]).read_text(encoding="utf-8"))
        gate.require(source_programs == {p: sha for p, sha in source_manifest.get("files", {}).items()
                                        if not gate.should_preserve_path(p)},
                     "正式旧版实际程序字节与源 manifest 不一致")
        verify_programs(app, source_programs)
        seed_license(app)
        saved = save_formal_case(probe, app, source, work / ("save-" + source))
        before = preserved_data(app)
        gate.require("license.lic" in before and any(p.endswith("/siphon_autosave.json") for p in before)
                     and saved["path"] in before, "正式旧版未生成工况和自动保存资料，或缺少授权文件")
        package = request["assets"].get("patch_zip") or request["assets"]["full_zip"]
        result = run_installer(probe, app / "CanalHydraulicCalcUpdater.exe", app, Path(package),
            version=request["version"], current=source, output=work / ("install-" + source),
            is_patch=bool(request["assets"].get("patch_zip")))
        gate.require(result["result"]["success"] and not result["fallback_exercised"],
                     "正常用户数据触发补丁失败或全量回退")
        data_proof = verify_data(app, before)
        verify_programs(app, request["programs"])
        main = start_main(probe, app, request["version"])
        installs.append({"source": source, "installer": result, "main": main, "saved_case": saved,
                         "user_data_files": len(before), "user_data_hashes": data_proof,
                         "old_helper_sha256": updater._sha256_file(str(work / ("install-" + source) / "CanalHydraulicCalcUpdater.exe")),
                         "program_files": len(request["programs"])})
    for key in ("U01", "U02", "U03"):
        cases[key] = {"status": "passed", "evidence": installs}
    gate.write_json(report["report_path"], report)
    source = request["latest"]
    app = extract_package(baseline_package(request["baselines"][source], cache), work / "slow")
    seed_license(app)
    before = saved_data(app)
    target = app / "CanalHydraulicCalc.exe"
    original_hash = updater._sha256_file(str(target))
    with target.open("ab") as stream:
        stream.write(b"\0")
    patch = request["assets"].get("patch_zip")
    if not patch:
        # 即使只发布全量，也应在真实旧版上测试新助手的补丁回退能力。
        patch = work / "fallback-probe.zip"
        with zipfile.ZipFile(patch, "w") as archive:
            archive.writestr("patch_manifest.json", json.dumps({
                "type": "universal_patch", "version": request["version"], "min_version": source,
                "included_files": [target.name], "deleted": [],
                "allowed_source_hashes": {target.name: [original_hash]},
                "target_files": {target.name: request["programs"][target.name]},
            }))
            archive.write(candidate / target.name, target.name)
    full = Path(request["assets"]["full_zip"])
    with PackageServer(full.read_bytes(), slow_seconds=65) as server:
        slow = run_installer(probe, helper, app, Path(patch), version=request["version"], current=source,
            output=work / "slow-report", is_patch=True, qa=True, full_url=server.url(),
            full_sha=request["binding"]["full_zip"], timeout=300)
    gate.require(slow["result"]["success"] and slow["worker_on_background_thread"]
                 and slow["max_log_blocks"] <= 300, "正式助手慢速回退失败或界面日志无限增长")
    slow["user_data_hashes"] = verify_data(app, before)
    verify_programs(app, request["programs"])
    slow["full_zip_sha256"] = request["binding"]["full_zip"]
    slow["main"] = start_main(probe, app, request["version"])
    cases["U04"] = {"status": "passed", "evidence": slow}
    gate.write_json(report["report_path"], report)
    failures = []
    for name in ("html", "bad_checksum", "apply_rollback"):
        app, before, full, patch = synthetic_install(work / name, request["version"])
        old = (app / "program.txt").read_bytes()
        if name == "apply_rollback":
            metadata = {"type": "universal_patch", "version": request["version"], "min_version": "1.0.0",
                "included_files": ["program.txt"], "deleted": [],
                "allowed_source_hashes": {"program.txt": [hashlib.sha256(old).hexdigest()]},
                "target_files": {"program.txt": hashlib.sha256(b"unexpected-target").hexdigest()}}
            with zipfile.ZipFile(patch, "w") as archive:
                archive.writestr("patch_manifest.json", json.dumps(metadata))
                archive.writestr("program.txt", b"new-program")
        with PackageServer(full.read_bytes()) as server:
            result = run_installer(probe, helper, app, patch, version=request["version"], current="1.0.0",
                output=work / (name + "-report"), is_patch=True, qa=True,
                full_url="" if name == "apply_rollback" else server.url("html" if name == "html" else "full.zip"),
                full_sha="0" * 64)
        gate.require(not result["result"]["success"] and
                     result["result"]["rollback_status"] in {"not_needed", "completed"},
                     "失败安装没有明确停止或成功恢复旧程序")
        gate.require((app / "program.txt").read_bytes() == old, "失败安装破坏旧程序")
        verify_data(app, before)
        if name == "apply_rollback":
            gate.require(result["result"]["rollback_status"] == "completed", "覆盖失败未执行真实回滚")
        # 在同一目录中重新安装有效完整包，验证失败后可以正常重试。
        retry = run_installer(probe, helper, app, full, version=request["version"], current="1.0.0",
            output=work / (name + "-retry"), is_patch=False, qa=True)
        gate.require(retry["result"]["success"], "安装失败后无法正常重试")
        verify_data(app, before)
        failures.append({"scenario": name, "failed": result, "retry": retry})
    cases["U05"] = {"status": "passed", "evidence": {"native": failures[:2], "additional": "必要回归覆盖代理断流和超时策略"}}
    cases["U06"] = {"status": "passed", "evidence": {"native": failures[2:], "additional": "必要回归覆盖权限、空间及旧会话残留"}}
    cases["U07"] = {"status": "passed", "evidence": {"binding": request["binding"]}}


def invoke_button(hwnd, *, phase):
    """仅操作本轮自己启动窗口的可访问按钮，使用 Windows 自带 UI Automation。"""
    predicates = {
        "download": "$name.StartsWith('下载') -and -not $name.StartsWith('下载日志')",
        "install": "$name -eq '立即安装更新' -or $name -eq '立即安装并降级'",
        "confirm": "$name -eq '确定' -or $name -eq '是' -or $name -eq 'Yes' -or $name -eq 'OK'",
        "launch": "$name -eq '启动新版本'",
    }
    command = """
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]HWND)
if ('PHASE' -eq 'confirm' -and $root.Current.Name -ne '确认更新') {
    $confirmTitle = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty, '确认安装更新')
    if ($null -eq $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $confirmTitle)) { return }
}
$condition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
$buttons = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
foreach ($button in $buttons) {
    $name = $button.Current.Name
    if (($button.Current.IsEnabled) -and -not ($button.Current.IsOffscreen) -and (PREDICATE)) {
        $pattern = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $pattern.Invoke()
        Write-Output 'invoked'
        break
    }
}
""".replace("HWND", str(int(hwnd))).replace("PHASE", phase).replace("PREDICATE", predicates[phase])
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, encoding="utf-8", errors="replace", timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW)
    gate.require(result.returncode == 0, "Windows 原生按钮验收接口不可用")
    return "invoked" in result.stdout


def online_acceptance(request, report, probe):
    gate.require(gate.read_json_url(request["manifest_url"]) == request["version_data"],
                 "正式客户端清单仍不可见或内容错误")
    work = Path(request["work_root"])
    work.mkdir(parents=True, exist_ok=False)
    cache = work / "cache"
    cache.mkdir()
    source = request["latest"]
    use_patch = bool(request["version_data"].get("patch_url"))
    package_sha = request["binding"]["patch_zip" if use_patch else "full_zip"]
    app = extract_package(baseline_package(request["baselines"][source], cache), work / "base")
    before = saved_data(app)
    old_helper_sha = updater._sha256_file(str(app / "CanalHydraulicCalcUpdater.exe"))
    process = subprocess.Popen([str(app / "CanalHydraulicCalc.exe"), updater.UPDATE_FLAG_OPEN_DIALOG], cwd=app)
    known_pids, observations = {process.pid}, []
    directories = [app]
    phases = set()
    main_samples, data_proof = [], None
    session = None
    session_file = None
    begin = time.monotonic()
    try:
        while time.monotonic() - begin < 1200:
            known_pids.update(probe.descendants(process.pid))
            session_files = list((Path(updater._get_update_log_root()) / "logs").glob("*/session.json"))
            for file in session_files:
                try:
                    data = json.loads(file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if Path(data.get("app_dir", "")).resolve() == app.resolve():
                    session, session_file = data, file
            directories = [app]
            if session:
                directories.append(Path(tempfile.gettempdir()) / ("canal-updater-runner-" + session["session_id"]))
                gate.require(session.get("is_patch") is use_patch
                             and session.get("expected_package_sha256") == package_sha,
                             "线上更新选择的包与本次已验收产物不一致")
            known_pids.update(probe.pids_in_directories(directories))
            windows = probe.windows(known_pids)
            observations.extend(windows)
            gate.require(all(w["responsive"] for w in windows), "线上更新界面失去响应")
            for window in windows:
                title = window["title"]
                if "安装更新" in title and "确认" not in title:
                    phases.add("helper")
                elif "install" in phases and "confirm" not in phases and window["pid"] == process.pid:
                    if invoke_button(window["hwnd"], phase="confirm"):
                        phases.add("confirm")
                elif "更新" in title:
                    if "确认" in title:
                        if invoke_button(window["hwnd"], phase="confirm"):
                            phases.add("confirm")
                    elif "install" not in phases and invoke_button(window["hwnd"], phase="install"):
                        phases.add("install")
                    elif "download" not in phases and invoke_button(window["hwnd"], phase="download"):
                        phases.add("download")
            if session:
                logs = list(Path(session["log_dir"]).glob("*.log"))
                text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in logs)
                gate.require("正在改用完整安装包" not in text or not use_patch,
                             "正常旧版线上更新误转全量包")
                if "安装完成" in text:
                    if "installed" not in phases:
                        verify_programs(app, request["programs"])
                        data_proof = verify_data(app, before)
                        phases.add("installed")
                    for window in windows:
                        if "安装更新" in window["title"] and "launch" not in phases:
                            if invoke_button(window["hwnd"], phase="launch"):
                                phases.add("launch")
            if "launch" in phases:
                main_samples.extend(w for w in windows if f"V{request['version']}" in w["title"])
                if len(main_samples) >= 4:
                    break
            time.sleep(1)
        gate.require({"download", "install", "helper", "installed", "launch"}.issubset(phases)
                     and session and len(main_samples) >= 4,
                     "没有完成正式旧版应用内下载和安装全过程")
        gate.require(session["target_version"] == request["version"],
                     "线上实际下载包未绑定本次发布产物")
        gate.require(probe.close_directories(directories, required_pids={w["pid"] for w in main_samples}),
                     "线上更新完成后新版程序或助手不能正常关闭")
        main = {"main_window_samples": len(main_samples), "normal_exit": True, "launch_button_used": True}
        report["cases"]["U09"] = {"status": "passed", "evidence": {
            "source": source, "old_helper_sha256": old_helper_sha, "phases": sorted(phases),
            "window_observations": len(observations), "unresponsive_observations": 0,
            "is_patch": use_patch, "package_sha256": package_sha,
            "main": main, "user_data_hashes": data_proof,
            "session_file": session_file.as_posix()}}
    except Exception:
        report["online_progress"] = {"phases": sorted(phases), "window_titles": sorted({w["title"] for w in observations})}
        raise
    finally:
        probe.close_directories(directories)
        if process.poll() is None:
            probe.close(process)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    report = {"binding": request["binding"], "cases": {}, "report_path": args.report}
    try:
        probe = WindowsProbe()
        work_root = Path(request["work_root"])
        isolate_profile(work_root.with_name(work_root.name + "-profile"))
        if request["mode"] == "local":
            local_acceptance(request, report, probe)
        else:
            online_acceptance(request, report, probe)
        gate.write_json(args.report, report)
        return 0
    except Exception as exc:
        report.update(error_type=type(exc).__name__, error=str(exc))
        gate.write_json(args.report, report)
        print(str(exc), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
