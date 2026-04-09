# -*- coding: utf-8 -*-
"""
应用内自动更新模块
功能：
1. 从 GitHub Gist 获取版本信息
2. 优先下载通用增量补丁包（覆盖所有 >= min_patch_version 的旧版本）
3. 版本不在补丁范围内、补丁不适用或下载失败时回退到全量包
4. 通过独立更新助手实现"关闭旧程序 → 覆盖文件 → 启动新程序"

更新源：GitHub Gist
下载优先级：通用补丁包 > 全量包
远程版本清单格式（version.json）：
{
    "latest_version": "1.0.7",
    "download_url": "https://github.com/.../CanalHydraulicCalc-V1.0.7.zip",
    "patch_url": "https://github.com/.../CanalHydraulicCalc-V1.0.7-patch.zip",
    "changelog": "- 修复xxx\\n- 新增xxx",
    "release_date": "2026-03-01",
    "min_version": "1.0.0",
    "file_size_mb": 286.5,
    "patch_size_mb": 5.2,
    "min_patch_version": "1.0.4"
}
"""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request
import urllib.error
import zipfile
import uuid
import subprocess
import fnmatch
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Callable

from version import APP_VERSION, APP_NAME_EN
from repo_config import (
    GITHUB_VERSION_URL as _GITHUB_VERSION_URL,
    DOWNLOAD_PROXIES as _DOWNLOAD_PROXIES,
)

_CHECK_TIMEOUT = 8  # 妫€鏌ユ洿鏂拌秴鏃讹紙绉掞級
_PROXY_PROBE_TIMEOUT = 5  # 代理探测超时（秒）
PROGRESS_THROTTLE_SECONDS = 0.5


# ============================================================
# 鐗堟湰姣旇緝
# ============================================================
def _parse_version(v: str) -> tuple:
    """将版本字符串解析为可比较的 4 段整数元组。"""
    if not isinstance(v, str):
        return (0, 0, 0, 0)
    nums = re.findall(r"\d+", v)
    if not nums:
        return (0, 0, 0, 0)
    parts = [int(x) for x in nums[:4]]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def compare_versions(a: str, b: str) -> int:
    """
    比较两个版本号。
    Returns:
        1  -> a > b
        0  -> a == b
        -1 -> a < b
    """
    pa = _parse_version(a)
    pb = _parse_version(b)
    if pa > pb:
        return 1
    if pa < pb:
        return -1
    return 0


def is_newer(remote_ver: str, local_ver: str = APP_VERSION) -> bool:
    """远程版本是否比本地版本新。"""
    return compare_versions(remote_ver, local_ver) > 0


# ============================================================
# 妫€鏌ユ洿鏂?# ============================================================
class UpdateInfo:
    """从远程版本清单解析出的更新信息"""

    def __init__(self, data: dict):
        self.latest_version: str = data.get("latest_version", "0.0.0")
        # 优先使用直连地址，由客户端统一决定是否套代理。
        self.download_url: str = data.get("download_url_direct") or data.get("download_url", "")
        self.patch_url: str = data.get("patch_url_direct") or data.get("patch_url", "")
        self.source: str = data.get("source", "")
        self.channel: str = data.get("channel", "")
        self.changelog: str = data.get("changelog", "")
        self.release_date: str = data.get("release_date", "")
        self.min_version: str = data.get("min_version", "0.0.0")
        self.file_size_mb: float = data.get("file_size_mb", 0)
        self.patch_size_mb: float = data.get("patch_size_mb", 0)
        self.min_patch_version: str = data.get("min_patch_version", "")
        self.download_url_proxy: str = data.get("download_url_proxy", "")
        self.patch_url_proxy: str = data.get("patch_url_proxy", "")
        self.allow_downgrade: bool = False
        # 兼容旧版 version.json 中的 patch_base_version 字段
        if not self.min_patch_version:
            self.min_patch_version = data.get("patch_base_version", "")

    @property
    def version_cmp(self) -> int:
        return compare_versions(self.latest_version, APP_VERSION)

    @property
    def is_newer_than_local(self) -> bool:
        return self.version_cmp > 0

    @property
    def is_older_than_local(self) -> bool:
        return self.version_cmp < 0

    @property
    def can_offer_downgrade(self) -> bool:
        """
        正式通道可提供“降级安装”入口：
        - 远程正式版低于当前本地版本
        - 存在可下载全量包
        """
        return (
            self.is_older_than_local
            and bool(self.download_url)
        )

    @property
    def has_update(self) -> bool:
        return self.is_newer_than_local or (
            self.allow_downgrade and self.can_offer_downgrade
        )

    @property
    def is_forced(self) -> bool:
        """当前版本低于最低要求版本时，强制更新"""
        return compare_versions(APP_VERSION, self.min_version) < 0

    @property
    def has_patch(self) -> bool:
        """是否提供了增量补丁包"""
        return bool(self.patch_url)

    @property
    def can_use_patch(self) -> bool:
        """当前版本是否可以使用通用补丁包（范围判断：APP_VERSION >= min_patch_version）"""
        if not self.has_patch:
            return False
        if not self.min_patch_version:
            return True
        return compare_versions(APP_VERSION, self.min_patch_version) >= 0


def _check_remote(url: str, source_name: str) -> Optional[UpdateInfo]:
    """浠庤繙绋?URL 璇诲彇鐗堟湰淇℃伅"""
    try:
        if not url:
            return None
        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"{APP_NAME_EN}/{APP_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=_CHECK_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        info = UpdateInfo(data)
        info.source = source_name
        return info
    except Exception:
        return None


def check_for_update(allow_downgrade: bool = False) -> Optional[UpdateInfo]:
    """
    Check updates from GitHub.
    Args:
        allow_downgrade: 是否允许在正式通道提供降级入口
    Returns:
        UpdateInfo or None
    """
    info = _check_remote(_GITHUB_VERSION_URL, "github:prod")
    if info is not None:
        info.allow_downgrade = bool(allow_downgrade)
        return info

    return None

# ============================================================
# 代理探测：自动选择最快下载源
# ============================================================
def _pick_fastest_url(url: str) -> str:
    """
    并发探测各代理前缀，返回第一个响应成功的完整 URL。
    探测失败或超时则跳过，全部失败时返回原始直连 URL。
    """
    import threading

    if not url.startswith("https://github.com/"):
        return url  # 非 GitHub URL 不走代理

    candidates = []
    for prefix in _DOWNLOAD_PROXIES:
        candidates.append(prefix + url if prefix else url)

    result_holder = [None]
    found_event = threading.Event()

    def _probe(candidate_url: str):
        try:
            req = urllib.request.Request(
                candidate_url, method="HEAD",
                headers={"User-Agent": f"{APP_NAME_EN}/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=_PROXY_PROBE_TIMEOUT) as resp:
                if resp.status < 400 and not found_event.is_set():
                    result_holder[0] = candidate_url
                    found_event.set()
        except Exception:
            pass

    threads = [threading.Thread(target=_probe, args=(c,), daemon=True) for c in candidates]
    for t in threads:
        t.start()
    found_event.wait(timeout=_PROXY_PROBE_TIMEOUT + 1)

    chosen = result_holder[0] or url
    if chosen != url:
        prefix_used = chosen[: len(chosen) - len(url)]
        print(f"[updater] 使用代理加速: {prefix_used}")
    return chosen


def _strip_proxy_prefix(url: str) -> str:
    """去掉代理前缀，还原为 GitHub 直连 URL（用于兜底重试）"""
    for prefix in _DOWNLOAD_PROXIES:
        if prefix and url.startswith(prefix):
            return url[len(prefix):]
    return url


class PartialDownloadError(Exception):
    """多线程分段下载部分失败时抛出，保留已下载内容供断点续传"""
    def __init__(self, dest_path: str, segments: list, failed_indices: set, total: int):
        self.dest_path = dest_path
        self.segments = segments          # list of (start, end)
        self.failed_indices = failed_indices  # 失败的分段下标集合
        self.total = total
        super().__init__(f"{len(failed_indices)}/{len(segments)} segments failed")


# ============================================================
# 涓嬭浇鏇存柊鍖?# ============================================================
_NUM_WORKERS = max(1, min(16, int(os.getenv("UPDATER_DOWNLOAD_WORKERS", "8"))))
_CHUNK_SIZE = 1024 * 1024  # 1MB per read


def _download_segment(
    url: str, start: int, end: int, dest_path: str,
    progress_arr: list, seg_idx: int,
    cancel_event=None,
):
    """涓嬭浇文件的?[start, end] 字节段基到 dest_path"""
    headers = {
        "User-Agent": f"{APP_NAME_EN}/updater",
        "Range": f"bytes={start}-{end}",
    }
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req, timeout=120)
    with open(dest_path, "r+b") as f:
        f.seek(start)
        while True:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("download cancelled")
            chunk = resp.read(_CHUNK_SIZE)
            if not chunk:
                break
            f.write(chunk)
            progress_arr[seg_idx] += len(chunk)


def _download_from_url(
    url: str,
    dest_dir: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_event=None,
) -> str:
    """浠?HTTP URL 涓嬭浇 zip锛堟敮鎺佸绾跨▼鍒嗘骞跺彂锛?"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    url = _pick_fastest_url(url)  # 自动选择最快代理
    filename = url.rsplit("/", 1)[-1] or f"{APP_NAME_EN}-update.zip"
    dest_path = os.path.join(dest_dir, filename)

    # 鐢?HEAD 璇锋眰鎺㈡祴鏂囦欢澶у皬鍜?Range 鏀寔锛堥伩鍏嶄笅杞芥暣涓枃浠讹級
    req = urllib.request.Request(
        url, method="HEAD",
        headers={"User-Agent": f"{APP_NAME_EN}/{APP_VERSION}"},
    )
    resp = urllib.request.urlopen(req, timeout=60)
    total = int(resp.headers.get("Content-Length", 0))
    accept_ranges = resp.headers.get("Accept-Ranges", "").lower() == "bytes"
    resp.close()

    if total <= 0 or total < 10 * 1024 * 1024 or not accept_ranges:
        return _download_single(url, dest_path, total, progress_callback, cancel_event)

    with open(dest_path, "wb") as f:
        f.seek(total - 1)
        f.write(b"\0")

    # 鍒嗘
    num_workers = min(_NUM_WORKERS, max(1, total // (5 * 1024 * 1024)))
    seg_size = total // num_workers
    segments = []
    for i in range(num_workers):
        start = i * seg_size
        end = (total - 1) if i == num_workers - 1 else (start + seg_size - 1)
        segments.append((start, end))

    progress_arr = [0] * num_workers

    # 鍚姩杩涘害鐩戞帶
    _CB_INTERVAL = 0.2
    stop_event = threading.Event()

    def _report_progress():
        while not stop_event.is_set():
            if progress_callback:
                progress_callback(sum(progress_arr), total)
            stop_event.wait(_CB_INTERVAL)

    monitor = threading.Thread(target=_report_progress, daemon=True)
    monitor.start()

    # 并发下载，收集所有失败分段（不提前中止）
    future_to_idx: dict = {}
    failed_indices: set = set()
    cancelled = False
    try:
        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = []
            for i, (start, end) in enumerate(segments):
                fut = pool.submit(
                    _download_segment, url, start, end, dest_path,
                    progress_arr, i, cancel_event,
                )
                futures.append(fut)
                future_to_idx[fut] = i

            for fut in as_completed(futures):
                try:
                    fut.result()
                except InterruptedError:
                    cancelled = True
                    failed_indices.add(future_to_idx[fut])
                except Exception:
                    failed_indices.add(future_to_idx[fut])
    finally:
        stop_event.set()
        monitor.join(timeout=1)

    if cancelled:
        try:
            os.remove(dest_path)
        except OSError:
            pass
        raise InterruptedError("download cancelled")

    if failed_indices:
        # 保留已下载的分段，抛出专用异常供上层断点续传
        raise PartialDownloadError(dest_path, segments, failed_indices, total)

    if progress_callback:
        progress_callback(total, total)

    return dest_path


def _resume_segments(
    url: str,
    dest_path: str,
    segments: list,
    failed_indices: set,
    already_bytes: int,
    total: int,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_event=None,
) -> str:
    """
    仅重新下载失败的分段，复用已写入文件的其余分段（断点续传）。
    url 应为直连 GitHub URL。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    n = len(failed_indices)
    progress_arr = [0] * n
    stop_event = threading.Event()

    def _report():
        while not stop_event.is_set():
            if progress_callback:
                progress_callback(already_bytes + sum(progress_arr), total)
            stop_event.wait(0.2)

    monitor = threading.Thread(target=_report, daemon=True)
    monitor.start()

    try:
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = []
            for j, i in enumerate(sorted(failed_indices)):
                start, end = segments[i]
                fut = pool.submit(
                    _download_segment, url, start, end, dest_path,
                    progress_arr, j, cancel_event,
                )
                futures.append(fut)
            for fut in as_completed(futures):
                fut.result()  # 若直连也失败则直接抛出
    except Exception:
        try:
            os.remove(dest_path)
        except OSError:
            pass
        raise
    finally:
        stop_event.set()
        monitor.join(timeout=1)

    if progress_callback:
        progress_callback(total, total)

    return dest_path


def _download_single(
    url: str, dest_path: str, total: int,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_event=None,
) -> str:
    """骜汉绾垳跩涓嬭浇涓嬭。"""
    req = urllib.request.Request(
        url, headers={"User-Agent": f"{APP_NAME_EN}/{APP_VERSION}"}
    )
    resp = urllib.request.urlopen(req, timeout=60)
    if total <= 0:
        total = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    last_cb_time = 0.0
    _CB_INTERVAL = 0.2

    with open(dest_path, "wb") as f:
        while True:
            if cancel_event and cancel_event.is_set():
                break
            chunk = resp.read(_CHUNK_SIZE)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if progress_callback:
                now = time.monotonic()
                if now - last_cb_time >= _CB_INTERVAL:
                    progress_callback(downloaded, total)
                    last_cb_time = now

    if cancel_event and cancel_event.is_set():
        try:
            os.remove(dest_path)
        except OSError:
            pass
        raise InterruptedError("download cancelled")

    if progress_callback:
        progress_callback(downloaded, total)

    return dest_path


def download_update(
    url: str,
    dest_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    source: str = "",
    cancel_event=None,
) -> str:
    """
    Download update zip to local temp directory.
    source is kept for backward compatibility and is ignored now.
    如果代理下载失败，自动去掉代理前缀回退到 GitHub 直连重试。
    支持 cancel_event (threading.Event) 取消下载。
    """
    _ = source
    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="canal_update_")

    try:
        return _download_from_url(url, dest_dir, progress_callback, cancel_event)
    except InterruptedError:
        raise  # 取消不走代理回退逻辑
    except PartialDownloadError as e:
        # 代理中途断流：已下载分段保留，仅直连补全失败分段
        direct_url = _strip_proxy_prefix(url)
        if direct_url != url:
            already = sum(
                e.segments[i][1] - e.segments[i][0] + 1
                for i in range(len(e.segments))
                if i not in e.failed_indices
            )
            print(
                f"[updater] 代理中途失败 "
                f"({len(e.failed_indices)}/{len(e.segments)} 段)，"
                f"断点续传 {already // (1024*1024)} MB 已保留，"
                f"直连补全剩余分段"
            )
            # 进度重置到确认已完成的字节数，避免进度条回跳
            if progress_callback:
                progress_callback(already, e.total)
            try:
                return _resume_segments(
                    direct_url, e.dest_path, e.segments,
                    e.failed_indices, already, e.total, progress_callback,
                    cancel_event,
                )
            except Exception:
                try:
                    os.remove(e.dest_path)
                except OSError:
                    pass
                raise
        else:
            try:
                os.remove(e.dest_path)
            except OSError:
                pass
            raise
    except Exception:
        direct_url = _strip_proxy_prefix(url)
        if direct_url != url:
            print(f"[updater] 代理连接失败，回退直连: {direct_url}")
            return _download_from_url(direct_url, dest_dir, progress_callback, cancel_event)
        raise

# ============================================================
# 安装会话 / 独立更新助手
# ============================================================
UPDATE_HELPER_NAME = f"{APP_NAME_EN}Updater"
UPDATE_HELPER_EXE = f"{UPDATE_HELPER_NAME}.exe"
UPDATE_FLAG_OPEN_DIALOG = "--show-update-dialog"
UPDATE_FLAG_FORCE_FULL_PACKAGE = "--force-full-package"
DEFAULT_PRESERVE_PATTERNS = ["*.lic"]
INSTALL_SLACK_BYTES = 256 * 1024 * 1024
INTERNAL_WORK_DIR = "_update_sessions"
PATCH_MISSING_SENTINEL = "__MISSING__"
PATCH_DIRECTORY_SENTINEL = "__UNEXPECTED_DIRECTORY__"
RETRY_MODE_FULL_PACKAGE = "full_package"


class UpdatePreparationError(RuntimeError):
    """安装前检查失败。"""


class UpdateInstallError(RuntimeError):
    """安装阶段失败。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "apply_failed",
        user_message: Optional[str] = None,
        retry_mode: Optional[str] = None,
    ):
        super().__init__(message)
        self.code = code
        self.user_message = user_message or message
        self.retry_mode = retry_mode


@dataclass
class UpdateSession:
    session_id: str
    app_dir: str
    main_exe_path: str
    download_zip_path: str
    is_patch: bool
    target_version: str
    current_version: str
    log_dir: str
    cleanup_targets: list[str]
    preserve_patterns: list[str]
    parent_pid: int = 0
    work_dir: str = ""
    main_script_path: str = ""
    session_file: str = ""

    def to_payload(self) -> dict:
        payload = asdict(self)
        payload.pop("session_file", None)
        return payload

    def write(self, session_file: str) -> str:
        os.makedirs(os.path.dirname(session_file), exist_ok=True)
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(self.to_payload(), f, ensure_ascii=False, indent=2)
        self.session_file = session_file
        return session_file

    @classmethod
    def from_file(cls, session_file: str) -> "UpdateSession":
        with open(session_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["session_file"] = session_file
        return cls(**payload)


def _get_project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return _get_project_root()


def _get_main_entry() -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    return sys.executable, os.path.join(_get_project_root(), "main.py")


def _get_update_helper_entry() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(_get_app_dir(), UPDATE_HELPER_EXE)
    return os.path.join(_get_project_root(), "update_helper.py")


def _get_update_log_root() -> str:
    base_dir = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    root = os.path.join(base_dir, APP_NAME_EN, "updater")
    os.makedirs(root, exist_ok=True)
    return root


def _with_pythonpath(env: dict[str, str], project_root: str) -> dict[str, str]:
    env = env.copy()
    existing = env.get("PYTHONPATH", "")
    if existing:
        env["PYTHONPATH"] = os.pathsep.join([project_root, existing])
    else:
        env["PYTHONPATH"] = project_root
    return env


def _normalize_relpath(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _should_preserve(rel_path: str, patterns: list[str]) -> bool:
    normalized = _normalize_relpath(rel_path)
    name = os.path.basename(normalized)
    return any(
        fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(name, pattern)
        for pattern in patterns
    )


class _ThrottledProgressEmitter:
    """按固定时间间隔回报进度，避免日志和界面被高频刷新淹没。"""

    def __init__(self, interval_sec: Optional[float] = None):
        self.interval_sec = PROGRESS_THROTTLE_SECONDS if interval_sec is None else interval_sec
        self._last_emit_time: Optional[float] = None

    def emit(self, callback: Optional[Callable], *args, force: bool = False):
        """在允许时触发回调；force=True 时总是回报最后一次状态。"""
        if callback is None:
            return
        now = time.monotonic()
        if (
            force
            or self.interval_sec <= 0
            or self._last_emit_time is None
            or now - self._last_emit_time >= self.interval_sec
        ):
            callback(*args)
            self._last_emit_time = now


def _dir_size(
    path: str,
    ignored_names: Optional[set[str]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> int:
    ignored_names = ignored_names or set()
    total = 0
    scanned_files = 0
    progress_emitter = _ThrottledProgressEmitter()
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ignored_names]
        for filename in files:
            if filename in ignored_names:
                continue
            scanned_files += 1
            try:
                total += os.path.getsize(os.path.join(root, filename))
            except OSError:
                pass
            progress_emitter.emit(
                progress_callback,
                f"正在统计安装目录大小（已扫描 {scanned_files} 个文件）",
            )
    if scanned_files:
        progress_emitter.emit(
            progress_callback,
            f"正在统计安装目录大小（已扫描 {scanned_files} 个文件）",
            force=True,
        )
    return total


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_install_dir_writable(app_dir: Optional[str] = None) -> bool:
    app_dir = app_dir or _get_app_dir()
    marker = os.path.join(app_dir, f".update-write-test-{uuid.uuid4().hex}.tmp")
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(marker)
        return True
    except OSError:
        return False


def estimate_required_space(
    zip_path: str,
    is_patch: bool,
    app_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> int:
    app_dir = app_dir or _get_app_dir()
    zip_size = os.path.getsize(zip_path)
    app_size = _dir_size(
        app_dir,
        ignored_names={INTERNAL_WORK_DIR, "__pycache__"},
        progress_callback=progress_callback,
    )
    if is_patch:
        return zip_size * 2 + INSTALL_SLACK_BYTES
    return zip_size + app_size + INSTALL_SLACK_BYTES


def ensure_install_ready(
    zip_path: str,
    is_patch: bool,
    app_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    app_dir = app_dir or _get_app_dir()
    if not zip_path or not os.path.isfile(zip_path):
        raise UpdatePreparationError("未找到已下载的更新包，请重新下载后再试。")
    if not os.access(zip_path, os.R_OK):
        raise UpdatePreparationError("更新包无法读取，请重新下载后再试。")
    if not os.path.isdir(app_dir):
        raise UpdatePreparationError("当前安装目录不存在，无法继续安装。")
    if not is_install_dir_writable(app_dir):
        raise UpdatePreparationError(
            "当前软件目录没有写入权限，请将软件解压到普通目录后再更新。"
        )

    required_bytes = estimate_required_space(
        zip_path,
        is_patch,
        app_dir,
        progress_callback=progress_callback,
    )
    try:
        free_bytes = shutil.disk_usage(app_dir).free
    except OSError as exc:
        raise UpdatePreparationError(f"无法检查磁盘空间：{exc}") from exc
    if free_bytes < required_bytes:
        need_mb = required_bytes / (1024 * 1024)
        free_mb = free_bytes / (1024 * 1024)
        raise UpdatePreparationError(
            f"可用磁盘空间不足：当前约 {free_mb:.0f} MB，可至少需要 {need_mb:.0f} MB。"
        )

    return {
        "app_dir": app_dir,
        "zip_size": os.path.getsize(zip_path),
        "required_bytes": required_bytes,
        "free_bytes": free_bytes,
    }


def create_update_session(
    zip_path: str,
    is_patch: bool,
    target_version: str,
    *,
    current_version: str = APP_VERSION,
    preserve_patterns: Optional[list[str]] = None,
) -> str:
    app_dir = _get_app_dir()
    ensure_install_ready(zip_path, is_patch, app_dir=app_dir)

    session_id = uuid.uuid4().hex[:12]
    log_dir = os.path.join(_get_update_log_root(), "logs", session_id)
    work_dir = os.path.join(app_dir, INTERNAL_WORK_DIR, session_id)
    main_exe_path, main_script_path = _get_main_entry()

    session = UpdateSession(
        session_id=session_id,
        app_dir=app_dir,
        main_exe_path=main_exe_path,
        download_zip_path=os.path.abspath(zip_path),
        is_patch=bool(is_patch),
        target_version=target_version or APP_VERSION,
        current_version=current_version or APP_VERSION,
        log_dir=log_dir,
        cleanup_targets=[os.path.abspath(zip_path)],
        preserve_patterns=list(preserve_patterns or DEFAULT_PRESERVE_PATTERNS),
        parent_pid=os.getpid(),
        work_dir=work_dir,
        main_script_path=main_script_path,
    )
    session_file = os.path.join(log_dir, "session.json")
    return session.write(session_file)


def apply_update(zip_path: str, is_patch: bool = False) -> str:
    """兼容旧入口：现在返回更新会话文件路径。"""
    return create_update_session(
        zip_path,
        is_patch=is_patch,
        target_version=APP_VERSION,
        current_version=APP_VERSION,
    )


def _prefer_windowed_python() -> str:
    exe_path = Path(sys.executable)
    if exe_path.name.lower() == "python.exe":
        candidate = exe_path.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return sys.executable


def launch_updater_and_exit(session_path: str):
    helper_entry = _get_update_helper_entry()
    if not os.path.exists(helper_entry):
        raise UpdatePreparationError(f"未找到更新助手：{helper_entry}")

    env = os.environ.copy()
    cwd = None
    creationflags = 0
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)

    if getattr(sys, "frozen", False):
        cmd = [helper_entry, "--spawn-session", session_path]
    else:
        project_root = _get_project_root()
        env = _with_pythonpath(env, project_root)
        cwd = project_root
        cmd = [_prefer_windowed_python(), helper_entry, "--spawn-session", session_path]

    subprocess.Popen(
        cmd,
        env=env,
        cwd=cwd,
        creationflags=creationflags,
        close_fds=False,
    )
    sys.exit(0)


class _UpdateSessionLogger:
    def __init__(self, log_dir: str):
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, "install.log")

    def log(self, message: str):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {message}\n")

    def exception(self, message: str, exc: BaseException):
        self.log(f"{message}: {exc!r}")


def _wait_for_process_exit(pid: int, timeout_sec: int = 60):
    if pid <= 0:
        return
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not _process_exists(pid):
            return
        time.sleep(0.3)
    raise UpdateInstallError(
        "主程序仍未退出，请关闭软件后重试。",
        code="wait_timeout",
        user_message="软件还没有完全退出，请关闭后重新尝试安装。",
    )


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
        False,
        pid,
    )
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _clean_dir(path: str):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _ensure_parent(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _copy_tree_contents(src_dir: str, dst_dir: str):
    for root, _dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(root, src_dir)
        target_root = dst_dir if rel_root == "." else os.path.join(dst_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)
        for filename in files:
            shutil.copy2(os.path.join(root, filename), os.path.join(target_root, filename))


def _extract_zip(
    zip_path: str,
    extract_dir: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    _clean_dir(extract_dir)
    os.makedirs(extract_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()
            total_members = len(members)
            progress_emitter = _ThrottledProgressEmitter()
            for index, member in enumerate(members, start=1):
                zf.extract(member, extract_dir)
                progress_emitter.emit(progress_callback, index, total_members)
            if total_members:
                progress_emitter.emit(progress_callback, total_members, total_members, force=True)
    except zipfile.BadZipFile as exc:
        raise UpdateInstallError(
            f"更新包损坏：{zip_path}",
            code="invalid_archive",
            user_message="下载的更新包已损坏，请重新下载后再试。",
        ) from exc

    entries = [os.path.join(extract_dir, name) for name in os.listdir(extract_dir)]
    dirs = [path for path in entries if os.path.isdir(path)]
    files = [path for path in entries if os.path.isfile(path)]
    if len(dirs) == 1 and not files:
        return dirs[0]
    return extract_dir


def _collect_preserved_files(session: UpdateSession, preserve_dir: str) -> list[str]:
    preserved = []
    _clean_dir(preserve_dir)
    for root, dirs, files in os.walk(session.app_dir):
        rel_root = os.path.relpath(root, session.app_dir)
        if rel_root == ".":
            dirs[:] = [d for d in dirs if d != INTERNAL_WORK_DIR]
        else:
            dirs[:] = [d for d in dirs if not _should_preserve(os.path.join(rel_root, d), [])]
        for filename in files:
            rel_path = filename if rel_root == "." else os.path.join(rel_root, filename)
            if not _should_preserve(rel_path, session.preserve_patterns):
                continue
            src = os.path.join(session.app_dir, rel_path)
            dst = os.path.join(preserve_dir, rel_path)
            _ensure_parent(dst)
            shutil.copy2(src, dst)
            preserved.append(_normalize_relpath(rel_path))
    return preserved


def _restore_preserved_files(preserve_dir: str, app_dir: str):
    if not os.path.isdir(preserve_dir):
        return
    _copy_tree_contents(preserve_dir, app_dir)


def _move_app_entries_to_backup(session: UpdateSession, backup_dir: str):
    _clean_dir(backup_dir)
    os.makedirs(backup_dir, exist_ok=True)
    for name in os.listdir(session.app_dir):
        if name == INTERNAL_WORK_DIR:
            continue
        src = os.path.join(session.app_dir, name)
        dst = os.path.join(backup_dir, name)
        shutil.move(src, dst)


def _remove_current_installation(session: UpdateSession):
    for name in os.listdir(session.app_dir):
        if name == INTERNAL_WORK_DIR:
            continue
        target = os.path.join(session.app_dir, name)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        else:
            try:
                os.remove(target)
            except OSError:
                pass


def _restore_full_backup(session: UpdateSession, backup_dir: str):
    _remove_current_installation(session)
    if not os.path.isdir(backup_dir):
        return
    for name in os.listdir(backup_dir):
        shutil.move(os.path.join(backup_dir, name), os.path.join(session.app_dir, name))


def _load_patch_manifest(extract_root: str) -> dict:
    manifest_path = os.path.join(extract_root, "patch_manifest.json")
    if not os.path.isfile(manifest_path):
        raise UpdateInstallError(
            "补丁包缺少 patch_manifest.json，无法继续安装。",
            code="invalid_archive",
            user_message="补丁包内容不完整，请重新下载完整安装包后再试。",
            retry_mode=RETRY_MODE_FULL_PACKAGE,
        )
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_current_file_state_hash(app_dir: str, rel_path: str) -> str:
    target = os.path.join(app_dir, rel_path.replace("/", os.sep))
    if os.path.isdir(target):
        return PATCH_DIRECTORY_SENTINEL
    if not os.path.isfile(target):
        return PATCH_MISSING_SENTINEL
    return _sha256_file(target)


def _raise_patch_mismatch(message: str):
    raise UpdateInstallError(
        message,
        code="patch_mismatch",
        user_message="当前安装状态不适合直接应用补丁，请重新下载完整安装包后再试。",
        retry_mode=RETRY_MODE_FULL_PACKAGE,
    )


def _validate_patch_prerequisites(
    session: UpdateSession,
    patch_manifest: dict,
    progress_callback: Optional[Callable[[int, int], None]] = None,
):
    min_version = (patch_manifest.get("min_version") or "").strip()
    if min_version and compare_versions(session.current_version, min_version) < 0:
        _raise_patch_mismatch(
            f"当前版本 {session.current_version} 低于补丁最低要求 {min_version}。"
        )

    allowed_source_hashes = patch_manifest.get("allowed_source_hashes")
    if not isinstance(allowed_source_hashes, dict) or not allowed_source_hashes:
        _raise_patch_mismatch("补丁包缺少 allowed_source_hashes，无法验证源文件状态。")

    watched_paths = sorted(
        {
            _normalize_relpath(path)
            for path in (patch_manifest.get("included_files") or []) + patch_manifest.get("deleted", [])
        }
    )
    effective_paths = [
        rel_path
        for rel_path in watched_paths
        if not _should_preserve(rel_path, session.preserve_patterns)
    ]
    total_paths = len(effective_paths)
    for index, rel_path in enumerate(effective_paths, start=1):
        if progress_callback:
            progress_callback(index, total_paths)
        allowed_values = allowed_source_hashes.get(rel_path)
        if not isinstance(allowed_values, list) or not allowed_values:
            _raise_patch_mismatch(f"补丁包缺少文件校验信息：{rel_path}")
        current_hash = _get_current_file_state_hash(session.app_dir, rel_path)
        if current_hash not in allowed_values:
            _raise_patch_mismatch(
                f"本机文件状态与补丁预期不一致：{rel_path} -> {current_hash}"
            )


def _prepare_patch_backup(session: UpdateSession, backup_dir: str, patch_manifest: dict) -> dict:
    _clean_dir(backup_dir)
    existing_backups: list[str] = []
    created_files: list[str] = []
    changed_files = patch_manifest.get("included_files") or (
        patch_manifest.get("added", []) + patch_manifest.get("modified", [])
    )
    deleted_files = patch_manifest.get("deleted", [])

    for rel_path in changed_files:
        normalized = _normalize_relpath(rel_path)
        if _should_preserve(normalized, session.preserve_patterns):
            continue
        target = os.path.join(session.app_dir, normalized.replace("/", os.sep))
        if os.path.exists(target):
            backup_target = os.path.join(backup_dir, normalized.replace("/", os.sep))
            _ensure_parent(backup_target)
            shutil.copy2(target, backup_target)
            existing_backups.append(normalized)
        else:
            created_files.append(normalized)

    for rel_path in deleted_files:
        normalized = _normalize_relpath(rel_path)
        if _should_preserve(normalized, session.preserve_patterns):
            continue
        target = os.path.join(session.app_dir, normalized.replace("/", os.sep))
        if os.path.exists(target) and normalized not in existing_backups:
            backup_target = os.path.join(backup_dir, normalized.replace("/", os.sep))
            _ensure_parent(backup_target)
            shutil.copy2(target, backup_target)
            existing_backups.append(normalized)

    return {
        "backed_up_files": existing_backups,
        "created_files": created_files,
    }


def _apply_patch_update(session: UpdateSession, extract_root: str, patch_manifest: dict):
    changed_files = patch_manifest.get("included_files") or (
        patch_manifest.get("added", []) + patch_manifest.get("modified", [])
    )
    for rel_path in changed_files:
        normalized = _normalize_relpath(rel_path)
        if _should_preserve(normalized, session.preserve_patterns):
            continue
        src = os.path.join(extract_root, normalized.replace("/", os.sep))
        if not os.path.isfile(src):
            raise UpdateInstallError(
                f"补丁包缺少文件：{normalized}",
                code="invalid_archive",
                user_message="补丁包内容不完整，请重新下载完整安装包后再试。",
                retry_mode=RETRY_MODE_FULL_PACKAGE,
            )
        dst = os.path.join(session.app_dir, normalized.replace("/", os.sep))
        _ensure_parent(dst)
        shutil.copy2(src, dst)

    for rel_path in patch_manifest.get("deleted", []):
        normalized = _normalize_relpath(rel_path)
        if _should_preserve(normalized, session.preserve_patterns):
            continue
        target = os.path.join(session.app_dir, normalized.replace("/", os.sep))
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        elif os.path.exists(target):
            os.remove(target)


def _rollback_patch(session: UpdateSession, backup_dir: str, patch_backup: dict):
    for rel_path in patch_backup.get("created_files", []):
        target = os.path.join(session.app_dir, rel_path.replace("/", os.sep))
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        elif os.path.exists(target):
            try:
                os.remove(target)
            except OSError:
                pass

    for rel_path in patch_backup.get("backed_up_files", []):
        src = os.path.join(backup_dir, rel_path.replace("/", os.sep))
        dst = os.path.join(session.app_dir, rel_path.replace("/", os.sep))
        if os.path.exists(src):
            _ensure_parent(dst)
            shutil.copy2(src, dst)


def _success_result(
    session: UpdateSession,
    log_path: str,
    work_dir: str,
    preserved_files: list[str],
) -> dict:
    return {
        "success": True,
        "session": session,
        "error_code": "",
        "user_message": "",
        "retry_mode": None,
        "rollback_ok": None,
        "log_path": log_path,
        "log_dir": session.log_dir,
        "work_dir": work_dir,
        "preserved_files": preserved_files,
    }


def _failure_result(
    session: UpdateSession,
    log_path: str,
    work_dir: str,
    exc: BaseException,
    *,
    rollback_ok: bool,
    rollback_error: Optional[BaseException] = None,
) -> dict:
    if rollback_error is not None:
        error_code = "rollback_failed"
        user_message = "安装失败，且自动回滚未能完成，请查看日志并重新解压完整安装包。"
        retry_mode = RETRY_MODE_FULL_PACKAGE
    elif isinstance(exc, UpdatePreparationError):
        error_code = "prepare_failed"
        user_message = str(exc)
        retry_mode = None
    elif isinstance(exc, UpdateInstallError):
        error_code = exc.code
        user_message = exc.user_message
        retry_mode = exc.retry_mode
    else:
        error_code = "apply_failed"
        user_message = "安装过程中发生异常，请重新下载后再试。"
        retry_mode = None

    return {
        "success": False,
        "session": session,
        "error_code": error_code,
        "user_message": user_message,
        "retry_mode": retry_mode,
        "rollback_ok": rollback_ok,
        "log_path": log_path,
        "log_dir": session.log_dir,
        "work_dir": work_dir,
        "error": str(exc),
    }


def run_update_session(
    session_path: str,
    *,
    stage_callback: Optional[Callable[[str, str], None]] = None,
) -> dict:
    session = UpdateSession.from_file(session_path)
    logger = _UpdateSessionLogger(session.log_dir)
    work_dir = session.work_dir or os.path.join(session.app_dir, INTERNAL_WORK_DIR, session.session_id)
    extract_dir = os.path.join(work_dir, "extract")
    backup_dir = os.path.join(work_dir, "backup")
    preserve_dir = os.path.join(work_dir, "preserved")
    session.work_dir = work_dir

    def push(stage_key: str, message: str):
        logger.log(message)
        if stage_callback:
            stage_callback(stage_key, message)

    preserved_files: list[str] = []
    patch_backup: dict = {}
    patch_manifest: Optional[dict] = None
    backup_ready = False

    try:
        push("prepare", "准备安装")
        os.makedirs(work_dir, exist_ok=True)

        push("wait", "等待主程序退出")
        _wait_for_process_exit(session.parent_pid)

        push("validate", "校验安装环境")
        ensure_install_ready(
            session.download_zip_path,
            session.is_patch,
            app_dir=session.app_dir,
            progress_callback=lambda text: push("validate", text),
        )
        if session.is_patch:
            push("validate", "正在解压补丁包")
        extracted_root = _extract_zip(
            session.download_zip_path,
            extract_dir,
            progress_callback=lambda current, total: push(
                "validate",
                (
                    f"正在解压补丁包（{current}/{total}）"
                    if session.is_patch
                    else f"正在解压完整安装包（{current}/{total}）"
                ),
            ),
        )
        if session.is_patch:
            patch_manifest = _load_patch_manifest(extracted_root)
            _validate_patch_prerequisites(
                session,
                patch_manifest,
                progress_callback=lambda current, total: push(
                    "validate",
                    f"正在校验补丁适用性（{current}/{total}）",
                ),
            )

        push("backup", "备份当前版本")
        if session.is_patch:
            patch_backup = _prepare_patch_backup(session, backup_dir, patch_manifest)
        else:
            preserved_files = _collect_preserved_files(session, preserve_dir)
            _move_app_entries_to_backup(session, backup_dir)
        backup_ready = True

        push("apply", "解压并应用更新")
        if session.is_patch:
            _apply_patch_update(session, extracted_root, patch_manifest or {})
        else:
            _copy_tree_contents(extracted_root, session.app_dir)
            _restore_preserved_files(preserve_dir, session.app_dir)

        push("cleanup", "清理临时文件")
        for target in session.cleanup_targets:
            try:
                if os.path.isdir(target):
                    shutil.rmtree(target, ignore_errors=True)
                elif os.path.exists(target):
                    os.remove(target)
            except OSError as exc:
                logger.exception("清理临时文件失败", exc)
        _clean_dir(work_dir)

        push("done", "安装完成")
        return _success_result(session, logger.log_path, work_dir, preserved_files)
    except Exception as exc:
        logger.exception("安装失败", exc)
        rollback_ok = False
        rollback_error: Optional[BaseException] = None
        if backup_ready:
            try:
                push("rollback", "安装失败，正在回滚")
                if session.is_patch:
                    _rollback_patch(session, backup_dir, patch_backup)
                else:
                    _restore_full_backup(session, backup_dir)
                rollback_ok = True
            except Exception as rollback_exc:
                logger.exception("回滚失败", rollback_exc)
                rollback_error = rollback_exc

        return _failure_result(
            session,
            logger.log_path,
            work_dir,
            exc,
            rollback_ok=rollback_ok,
            rollback_error=rollback_error,
        )



