# -*- coding: utf-8 -*-
"""正式发布的产物验收、远端回读及清单切换门槛。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

from tools import patch_builder, release_snapshot
from update_artifact_rules import is_runtime_artifact, should_preserve_path

LOCAL_CASES = tuple(f"U{i:02}" for i in range(1, 8))
REGRESSION_FILES = (
    "test_build_patch_floor_unit.py", "test_updater_install_flow_unit.py",
    "test_update_helper_unit.py", "test_updater_versioning_unit.py",
    "test_update_dialog_install_guard_unit.py", "test_release_snapshot_unit.py",
    "test_release_gitee_unit.py", "test_release_acceptance_unit.py",
    "test_release_gui_unit.py", "test_backfill_patch_release_unit.py",
    "test_update_acceptance_native_unit.py", "test_repair_runtime_patch_unit.py",
)


class AcceptanceError(RuntimeError):
    """验收失败必须阻止发布继续执行。"""


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def checked_path(name, *, directory=False):
    """按 Windows 解压语义拒绝可逃逸或落到同一路径的别名。"""
    require(isinstance(name, str) and name, "ZIP 含不安全路径")
    path = PurePosixPath(name)
    parts = name.rstrip("/").split("/") if directory else name.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    require(not path.is_absolute() and not any(char in name for char in '\\:<>"|?*')
            and not any(ord(char) < 32 for char in name)
            and all(part and part not in {".", ".."} and part == part.rstrip(" .")
                    and part.split(".")[0].upper() not in reserved for part in parts), "ZIP 含不安全路径")


def checked_members(archive):
    """拒绝路径逃逸、符号链接及 Windows 下可能互相覆盖的重复路径。"""
    members = {}
    names = set()
    for entry in archive.infolist():
        name = entry.orig_filename
        checked_path(name, directory=entry.is_dir())
        require(name == entry.filename, "ZIP 含不安全路径")
        require(((entry.external_attr >> 16) & 0o170000) != 0o120000, "ZIP 含符号链接")
        normalized = name.rstrip("/").casefold()
        require(normalized not in names, "ZIP 含重复路径")
        names.add(normalized)
        if not entry.is_dir():
            members[name] = entry
    return members


def zip_programs(path, *, allow_runtime=False):
    """全量包必须只有一个应用根目录；按实际字节计算程序清单。"""
    with zipfile.ZipFile(path) as archive:
        members = checked_members(archive)
        mains = [name for name in members if PurePosixPath(name).name == "CanalHydraulicCalc.exe"]
        require(len(mains) == 1, "全量包必须包含唯一的主程序")
        prefix = mains[0].rsplit("/", 1)[0] + "/" if "/" in mains[0] else ""
        programs = {}
        for name, entry in members.items():
            require(name.startswith(prefix), "全量包包含应用根目录以外的文件")
            relative = name[len(prefix):]
            if should_preserve_path(relative):
                require(allow_runtime, f"候选全量包夹带用户数据：{relative}")
                continue
            with archive.open(entry) as stream:
                programs[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
        require("CanalHydraulicCalcUpdater.exe" in programs, "全量包缺少独立更新助手")
        return prefix, programs


def inspect_candidate(version, assets):
    manifest_path = Path(assets.get("manifest_path", ""))
    require(manifest_path.is_file(), "缺少本次构建的目标 manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("version") == version, "目标 manifest 版本不一致")
    prefix, programs = zip_programs(assets["full_zip"])
    require(all(not should_preserve_path(p) for p in manifest.get("files", {})),
            "目标 manifest 包含用户数据")
    require(programs == manifest.get("files"), "实际全量包字节与目标 manifest 不一致")
    binding = {
        "version": version,
        "full_zip": release_snapshot.sha256_file(assets["full_zip"]),
        "manifest": release_snapshot.sha256_file(str(manifest_path)),
        "main_exe": programs["CanalHydraulicCalc.exe"],
        "helper_exe": programs["CanalHydraulicCalcUpdater.exe"],
    }
    metadata = None
    if assets.get("patch_zip"):
        with zipfile.ZipFile(assets["patch_zip"]) as archive:
            members = checked_members(archive)
            require("patch_manifest.json" in members, "补丁缺少元数据")
            metadata = json.loads(archive.read("patch_manifest.json"))
            require(metadata.get("type") == "universal_patch" and metadata.get("version") == version,
                    "补丁类型或版本不一致")
            require(metadata.get("target_files") == programs, "补丁目标与本次全量包不一致")
            included = metadata.get("included_files", [])
            deleted = metadata.get("deleted", [])
            watched = set(included) | set(deleted)
            for path in watched:
                checked_path(path)
            require(len(included) == len(set(included)) and len(deleted) == len(set(deleted)),
                    "补丁包含重复文件要求")
            require(not set(included) & set(deleted), "补丁覆盖和删除列表冲突")
            require(all(not should_preserve_path(p) for p in watched), "补丁会覆盖或删除用户数据")
            require(set(members) == {"patch_manifest.json", *included}, "补丁 payload 列表不一致")
            require(set(metadata.get("allowed_source_hashes", {})) == watched,
                    "补丁程序源状态要求不完整")
            for path in included:
                require(path in programs and hashlib.sha256(archive.read(path)).hexdigest() == programs[path],
                        f"补丁程序字节不一致：{path}")
            require(not set(deleted) & set(programs), "补丁会删除目标版本的程序文件")
        sources = metadata.get("source_versions", [])
        require(isinstance(sources, list) and sources and len(sources) == len(set(sources)),
                "补丁必须声明非重复的正式源版本")
        require(metadata.get("min_version") == min(sources, key=patch_builder._version_key),
                "补丁最低版本与覆盖范围不一致")
        require(all(patch_builder._version_key(v) < patch_builder._version_key(version) for v in sources),
                "补丁声明了非旧版本基线")
        require(assets.get("patch_min_version") == metadata["min_version"]
                and assets.get("patch_source_versions") == sources
                and assets.get("patch_changed_count") == len(included)
                and assets.get("patch_deleted_count") == len(deleted),
                "patch-info 发布字段与实际补丁元数据不一致")
        binding["patch_zip"] = release_snapshot.sha256_file(assets["patch_zip"])
    return binding, prefix, programs, metadata


def load_baselines(version, metadata, snapshot_root, previous_version=None):
    snapshots = {}
    root = Path(snapshot_root)
    for file in root.glob("v*/snapshot.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        source = data.get("version", "")
        if source and patch_builder._version_key(source) < patch_builder._version_key(version):
            snapshots[source] = data
    require(snapshots, "缺少可用于实际升级的正式旧版快照")
    latest = previous_version or max(snapshots, key=patch_builder._version_key)
    require(latest in snapshots, "缺少上一正式版本的快照")
    sources = metadata["source_versions"] if metadata else [latest]
    require(latest in sources, "补丁覆盖范围漏掉上一正式版本")
    for source in sources:
        require(source in snapshots, f"缺少已声明源版本的正式快照：{source}")
        manifest_path = Path(snapshots[source].get("manifest", {}).get("path", ""))
        require(manifest_path.is_file(), f"缺少正式源 manifest：{source}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(manifest.get("version") == source, f"正式源 manifest 版本不一致：{source}")
        if metadata:
            for path, allowed in metadata["allowed_source_hashes"].items():
                expected = manifest.get("files", {}).get(path, patch_builder.MISSING_FILE_SENTINEL)
                require(expected in allowed, f"补丁不适用于已声明基线：{source} / {path}")
    selected = {latest, min(sources, key=patch_builder._version_key)}
    # 最近发生故障的版本要保留在原生升级验收中。
    selected.update(v for v in ("1.4.5", "1.4.6") if v in sources)
    return {v: snapshots[v] for v in sorted(selected, key=patch_builder._version_key)}, latest


def run_regressions(root, python, output):
    """Qt 用例按文件独立进程运行，失败或跳过均不能作为通过。"""
    import xml.etree.ElementTree as ET
    reports = []
    env = dict(os.environ, PYTHONUTF8="1", QT_QPA_PLATFORM="offscreen")
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "1"
    for file in REGRESSION_FILES:
        path = Path(root) / "tests" / file
        require(path.is_file(), f"缺少必要回归：{file}")
        xml = Path(output) / (file + ".xml")
        log = Path(output) / (file + ".log")
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run(
                [python, "-m", "pytest", str(path), "-q", "-p", "no:hypothesispytest",
                 "--junitxml", str(xml), "--basetemp", str(Path(output) / (file + "-tmp"))],
                cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=180,
            )
        require(result.returncode == 0 and xml.is_file(), f"必要回归失败：{file}，日志：{log}")
        suites = list(ET.parse(xml).getroot().iter("testsuite"))
        counts = {key: sum(int(s.attrib.get(key, 0)) for s in suites)
                  for key in ("tests", "failures", "errors", "skipped")}
        require(counts["tests"] > 0 and not any(counts[k] for k in ("failures", "errors", "skipped")),
                f"必要回归不完整：{file}")
        reports.append({"file": file, **counts, "xml": str(xml)})
    return reports


def run_native(command, request, output, timeout=1200):
    request_path = Path(output) / "request.json"
    report_path = Path(output) / "native.json"
    write_json(request_path, request)
    # 只接收本次子进程新写的报告，旧的通过记录不可复用。
    if report_path.exists():
        report_path.unlink()
    env = dict(os.environ, PYTHONUTF8="1")
    env.pop("QT_QPA_PLATFORM", None)
    log = Path(output) / "native.log"
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run([*command, "--request", str(request_path), "--report", str(report_path)],
                                env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    require(result.returncode == 0 and report_path.is_file(), f"原生验收失败，日志：{log}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    require(report.get("binding") == request["binding"], "原生验收报告未绑定本次实际产物")
    expected = LOCAL_CASES if request["mode"] == "local" else ("U09",)
    for case in expected:
        item = report.get("cases", {}).get(case, {})
        require(item.get("status") == "passed" and item.get("evidence"), f"{case} 缺少通过证据")
    if request["mode"] == "local":
        saved_installs = report["cases"]["U02"]["evidence"]
        require({item["source"] for item in saved_installs} == set(request["baselines"]),
                "U02 缺少正式旧版的工况保存记录")
        for item in saved_installs:
            saved = item["saved_case"]
            hashes = item["user_data_hashes"]
            case_hash = hashes.get(saved["path"], {})
            authorization = hashes.get("license.lic", {})
            require(saved["normal_exit"] is True and saved["before_sha256"] != saved["saved_sha256"]
                    and case_hash.get("before_sha256") == case_hash.get("after_sha256") == saved["saved_sha256"]
                    and authorization.get("before_sha256") == authorization.get("after_sha256")
                    and bool(authorization.get("before_sha256")),
                    "U02 工况或授权前后数据无法核对")
        slow = report["cases"]["U04"]["evidence"]
        require(slow.get("download_seconds", 0) >= 60 and slow.get("heartbeat_count", 0) >= 100
                and 0 < slow.get("max_heartbeat_gap_ms", 0) <= 2000
                and slow.get("all_ui_callbacks_on_gui_thread") is True
                and slow.get("worker_on_background_thread") is True
                and slow.get("result", {}).get("success") is True
                and 0 < slow.get("max_log_blocks", 0) <= 300
                and slow.get("window_observations", 0) > 0
                and slow.get("unresponsive_observations") == 0
                and slow.get("fallback_exercised") is True and slow.get("speed_visible") is True
                and slow.get("full_zip_sha256") == request["binding"]["full_zip"]
                and slow.get("main", {}).get("normal_exit") is True,
                "慢速回退未达到原生助手验收门槛")
    else:
        online = report["cases"]["U09"]["evidence"]
        require(online.get("source") == request["latest"]
                and online.get("unresponsive_observations") == 0
                and online.get("main", {}).get("main_window_samples", 0) >= 4
                and online.get("main", {}).get("normal_exit") is True
                and online.get("main", {}).get("launch_button_used") is True,
                "应用内升级没有完成成功页启动及真实主窗口正常关闭")
    return report


def native_work_root(output):
    # Older Windows helpers need room for archive paths below their work directory.
    return str(Path(output).parents[2] / ".release-snapshots" / f"qa-{time.time_ns():x}")


@dataclass
class ReleaseAcceptance:
    version: str
    assets: dict
    binding: dict
    output: Path
    baselines: dict
    latest: str
    native_command: list[str]
    local_report: dict

    def assert_unchanged(self):
        binding, *_ = inspect_candidate(self.version, self.assets)
        require(binding == self.binding, "验收后的候选产物已改变，停止发布")

    def record(self, stage, data):
        self.local_report[stage] = data
        write_json(self.output / "acceptance.json", self.local_report)


def prepare_local(version, assets, *, root, python, snapshot_root=None, previous_version=None):
    """本地产物验证失败时，不会触发任何发布 API 或 Git 写操作。"""
    output = Path(root) / "outputs" / "release_acceptance" / f"v{version}-{time.time_ns()}"
    output.mkdir(parents=True)
    report = {"version": version, "status": "running", "created_at": datetime.now(timezone.utc).isoformat()}
    write_json(output / "acceptance.json", report)
    try:
        binding, prefix, programs, metadata = inspect_candidate(version, assets)
        baselines, latest = load_baselines(version, metadata, snapshot_root or Path(root) / ".release-snapshots",
                                           previous_version)
        # 封存真正验收和发布的字节，构建目录随后变化也不能换掉上传对象。
        sealed = dict(assets)
        sealed_dir = output / "artifacts"
        sealed_dir.mkdir()
        for key in ("full_zip", "patch_zip", "manifest_path"):
            if assets.get(key):
                destination = sealed_dir / Path(assets[key]).name
                shutil.copy2(assets[key], destination)
                sealed[key] = str(destination)
        require(inspect_candidate(version, sealed)[0] == binding, "封存候选产物时字节发生变化")
        regressions = run_regressions(root, python, output)
        command = [python, str(Path(root) / "tools" / "update_acceptance_native.py")]
        request = {"mode": "local", "version": version, "assets": sealed, "binding": binding,
                   "prefix": prefix, "programs": programs, "baselines": baselines, "latest": latest,
                   "work_root": native_work_root(output)}
        native = run_native(command, request, output)
        report.update(status="local_passed", binding=binding, regressions=regressions, local=native)
        changes = subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=root, capture_output=True, check=True)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, check=True)
        # 只记录改动指纹，不将本地差异文本或授权资料写入验收报告。
        report["source"] = {"head": head.stdout.decode("ascii").strip(),
                            "tracked_diff_sha256": hashlib.sha256(changes.stdout).hexdigest(),
                            "files": {name: release_snapshot.sha256_file(str(Path(root) / name)) for name in (
                                "updater.py", "update_helper.py", "update_artifact_rules.py", "tools/build.py",
                                "tools/patch_builder.py", "tools/release.py", "tools/release_acceptance.py",
                                "tools/update_acceptance_native.py", "tools/update_acceptance_saved_data.py")}}
        write_json(output / "acceptance.json", report)
        gate = ReleaseAcceptance(version, sealed, binding, output, baselines, latest, command, report)
        gate.assert_unchanged()
        return gate
    except BaseException as exc:
        report.update(status="failed", failed_stage="local", error_type=type(exc).__name__)
        if isinstance(exc, AcceptanceError):
            report["error"] = str(exc)
        write_json(output / "acceptance.json", report)
        raise


def read_json_url(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "CanalHydraulicCalc/acceptance"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_manifest(url, expected, *, deadline_seconds=420):
    """等待普通客户端地址一致可见，不能用加参数或 API 绕过缓存验收。"""
    end = time.monotonic() + deadline_seconds
    while True:
        try:
            if read_json_url(url, timeout=min(15, max(1, end - time.monotonic()))) == expected:
                return {"url": url, "status": "passed", "ordinary_url": True}
        except (OSError, ValueError):
            pass
        require(time.monotonic() < end, "客户端普通更新清单在时限内未与预期一致")
        time.sleep(min(2, max(0, end - time.monotonic())))


def verify_download(url, expected_sha, expected_size, *, opener=None, deadline_seconds=900):
    """必须完整回读，不能用 HEAD、平台摘要或 HTTP 200 代替。"""
    opener = opener or urllib.request.urlopen
    digest, size = hashlib.sha256(), 0
    begin = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "CanalHydraulicCalc/acceptance"})
    with opener(request, timeout=30) as response:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        require(response.status == 200 and not content_type.startswith("text/")
                and content_type not in {"application/json", "application/xhtml+xml"},
                "远端响应不是完整更新文件")
        while chunk := response.read(256 * 1024):
            size += len(chunk)
            require(size <= expected_size and time.monotonic() - begin <= deadline_seconds,
                    "远端更新文件超出预期大小或回读时限")
            digest.update(chunk)
    require(size == expected_size and digest.hexdigest() == expected_sha, "远端更新文件大小或 SHA256 不一致")
    return {"url": url, "sha256": digest.hexdigest(), "size_bytes": size,
            "method": "complete_download", "seconds": round(time.monotonic() - begin, 3)}


def verify_remote(gate, version_data):
    gate.assert_unchanged()
    targets = {}
    require(version_data.get("latest_version") == gate.version, "正式清单目标版本未绑定验收版本")
    require(version_data.get("file_size_mb") == round(Path(gate.assets["full_zip"]).stat().st_size / (1024*1024), 1),
            "正式清单全量包大小与实际字节不一致")
    if version_data.get("patch_url"):
        require(version_data.get("patch_size_mb") == round(Path(gate.assets["patch_zip"]).stat().st_size / (1024*1024), 2)
                and version_data.get("min_patch_version") == gate.assets["patch_min_version"]
                and version_data.get("patch_base_version") == gate.assets["patch_min_version"],
                "正式清单补丁大小或最低版本与实际补丁不一致")
    for name, key, sha_key in (("download", "full_zip", "download_sha256"), ("patch", "patch_zip", "patch_sha256")):
        if name == "patch" and not version_data.get("patch_url"):
            continue
        require(version_data.get(sha_key) == gate.binding[key], "清单校验值未绑定已验收包")
        require(version_data.get(name + "_url"), "正式清单缺少主下载地址")
        urls = [version_data.get(name + "_url"), version_data.get(name + "_url_direct"),
                version_data.get(name + "_url_proxy"), *version_data.get(name + "_url_mirrors", [])]
        for url in filter(None, urls):
            require(url.startswith("https://"), "正式更新地址必须使用 HTTPS")
            target = (gate.binding[key], Path(gate.assets[key]).stat().st_size)
            require(url not in targets or targets[url] == target, "不同更新包共用了下载地址")
            targets[url] = target
    require(targets, "缺少正式更新文件地址")
    verified = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(verify_download, url, *expected): url for url, expected in targets.items()}
        for future in as_completed(futures):
            try:
                verified.append(future.result())
            except Exception as exc:
                gate.record("remote", {"status": "failed", "error_type": type(exc).__name__, "verified": verified})
                gate.record("status", "failed")
                raise AcceptanceError("U08 远端附件验收失败，保留旧正式清单") from exc
    gate.assert_unchanged()
    receipt = {"status": "passed", "binding": dict(gate.binding), "version_data": dict(version_data),
               "verified": verified}
    gate.record("remote", receipt)
    return receipt


def require_remote_receipt(gate, version_data):
    gate.assert_unchanged()
    receipt = gate.local_report.get("remote", {})
    require(receipt.get("status") == "passed" and receipt.get("binding") == gate.binding
            and receipt.get("version_data") == version_data, "未通过本次远端验收，禁止切换 Gist")


def verify_online(gate, version_data, manifest_url):
    require_remote_receipt(gate, version_data)
    ordinary = wait_for_manifest(manifest_url, version_data)
    prefix, programs = zip_programs(gate.assets["full_zip"])
    request = {"mode": "online", "version": gate.version, "assets": gate.assets, "binding": gate.binding,
               "prefix": prefix, "programs": programs, "baselines": gate.baselines, "latest": gate.latest,
               "version_data": version_data, "manifest_url": manifest_url,
               "work_root": native_work_root(gate.output)}
    output = gate.output / "online"
    output.mkdir()
    native = run_native(gate.native_command, request, output, timeout=1500)
    native["ordinary_manifest"] = ordinary
    gate.record("online", native)
    gate.assert_unchanged()
    return native
