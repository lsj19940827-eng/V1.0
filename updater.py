# -*- coding: utf-8 -*-
"""
应用内自动更新模块
功能：
1. 从 GitHub Gist 获取版本信息，Gitee 作为回退
2. 优先下载通用增量补丁包（覆盖所有 >= min_patch_version 的旧版本）
3. 版本不在补丁范围内或下载失败时回退到全量包
4. 通过 .bat 脚本实现"关闭旧程序 → 覆盖文件 → 启动新程序"

更新源优先级：GitHub Gist > Gitee
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

import json
import os
import shutil
import sys
import tempfile
import textwrap
import time
import urllib.request
import urllib.error
from typing import Optional, Callable

from version import APP_VERSION, APP_NAME_EN
from repo_config import (
    GITHUB_VERSION_URL as _GITHUB_VERSION_URL,
    GITEE_VERSION_URL as _GITEE_VERSION_URL,
    DOWNLOAD_PROXIES as _DOWNLOAD_PROXIES,
)

_CHECK_TIMEOUT = 8  # 妫€鏌ユ洿鏂拌秴鏃讹紙绉掞級
_PROXY_PROBE_TIMEOUT = 5  # 代理探测超时（秒）


# ============================================================
# 鐗堟湰姣旇緝
# ============================================================
def _parse_version(v: str) -> tuple:
    """灏?'1.0.2' 瑙ｆ瀽涓?(1, 0, 2) 浠ヤ究姣旇緝"""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def is_newer(remote_ver: str, local_ver: str = APP_VERSION) -> bool:
    """杩滅▼鐗堟湰鏄惁姣旀湰鍦扮増鏈洿鏂?"""
    return _parse_version(remote_ver) > _parse_version(local_ver)


# ============================================================
# 妫€鏌ユ洿鏂?# ============================================================
class UpdateInfo:
    """从远程版本清单解析出的更新信息"""

    def __init__(self, data: dict):
        self.latest_version: str = data.get("latest_version", "0.0.0")
        self.download_url: str = data.get("download_url", "")
        self.patch_url: str = data.get("patch_url", "")
        self.source: str = data.get("source", "")
        self.changelog: str = data.get("changelog", "")
        self.release_date: str = data.get("release_date", "")
        self.min_version: str = data.get("min_version", "0.0.0")
        self.file_size_mb: float = data.get("file_size_mb", 0)
        self.patch_size_mb: float = data.get("patch_size_mb", 0)
        self.min_patch_version: str = data.get("min_patch_version", "")
        # 兼容旧版 version.json 中的 patch_base_version 字段
        if not self.min_patch_version:
            self.min_patch_version = data.get("patch_base_version", "")

    @property
    def has_update(self) -> bool:
        return is_newer(self.latest_version)

    @property
    def is_forced(self) -> bool:
        """当前版本低于最低要求版本时，强制更新"""
        return _parse_version(APP_VERSION) < _parse_version(self.min_version)

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
        return _parse_version(APP_VERSION) >= _parse_version(self.min_patch_version)


def _check_remote(url: str, source_name: str) -> Optional[UpdateInfo]:
    """浠庤繙绋?URL 璇诲彇鐗堟湰淇℃伅"""
    try:
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


def check_for_update() -> Optional[UpdateInfo]:
    """
    Check updates with GitHub as primary source and Gitee as fallback.
    Returns:
        UpdateInfo or None
    """
    info = _check_remote(_GITHUB_VERSION_URL, "github")
    if info is not None:
        return info

    info = _check_remote(_GITEE_VERSION_URL, "gitee")
    if info is not None:
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
):
    """涓嬭浇鏂囦欢鐨?[start, end] 瀛楄妭娈靛埌 dest_path"""
    headers = {
        "User-Agent": f"{APP_NAME_EN}/updater",
        "Range": f"bytes={start}-{end}",
    }
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req, timeout=120)
    with open(dest_path, "r+b") as f:
        f.seek(start)
        while True:
            chunk = resp.read(_CHUNK_SIZE)
            if not chunk:
                break
            f.write(chunk)
            progress_arr[seg_idx] += len(chunk)


def _download_from_url(
    url: str,
    dest_dir: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
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
        return _download_single(url, dest_path, total, progress_callback)

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
    try:
        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = []
            for i, (start, end) in enumerate(segments):
                fut = pool.submit(
                    _download_segment, url, start, end, dest_path,
                    progress_arr, i,
                )
                futures.append(fut)
                future_to_idx[fut] = i

            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception:
                    failed_indices.add(future_to_idx[fut])
    finally:
        stop_event.set()
        monitor.join(timeout=1)

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
                    progress_arr, j,
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
) -> str:
    """鍗曠嚎绋嬩笅杞藉洖閫€"""
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

    if progress_callback:
        progress_callback(downloaded, total)

    return dest_path


def download_update(
    url: str,
    dest_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    source: str = "",
) -> str:
    """
    Download update zip to local temp directory.
    source is kept for backward compatibility and is ignored now.
    如果代理下载失败，自动去掉代理前缀回退到 GitHub 直连重试。
    """
    _ = source
    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="canal_update_")

    try:
        return _download_from_url(url, dest_dir, progress_callback)
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
            try:
                return _resume_segments(
                    direct_url, e.dest_path, e.segments,
                    e.failed_indices, already, e.total, progress_callback,
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
            return _download_from_url(direct_url, dest_dir, progress_callback)
        raise

# ============================================================
# 搴旂敤鏇存柊锛堢敓鎴?.bat 鑴氭湰骞舵墽琛岋級
# ============================================================
def _get_app_dir() -> str:
    """鑾峰彇褰撳墠搴旂敤绋嬪簭鎵€鍦ㄧ洰褰?"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def apply_update(zip_path: str, is_patch: bool = False) -> str:
    """
    鐢熸垚鏇存柊鐢?.bat 鑴氭湰銆?
    鍏ㄩ噺妯″紡 (is_patch=False): 澶囦唤鍏ㄩ儴鏃ф枃浠?-> 瑙ｅ帇鏂?zip 瑕嗙洊 -> 鍚姩
    琛ヤ竵妯″紡 (is_patch=True):  瑙ｅ帇琛ヤ竵 zip 鐩存帴瑕嗙洊鍙樺寲鏂囦欢 -> 鍒犻櫎宸茬Щ闄ゆ枃浠?-> 鍚姩

    Args:
        zip_path: 宸蹭笅杞界殑 zip 鏂囦欢璺緞
        is_patch: 鏄惁涓哄閲忚ˉ涓佸寘

    Returns:
        鐢熸垚鐨?bat 鏂囦欢璺緞锛堣皟鐢ㄦ柟搴斿湪鎵ц鍚庨€€鍑轰富绋嬪簭锛?    """
    app_dir = _get_app_dir()
    exe_name = f"{APP_NAME_EN}.exe"
    bat_path = os.path.join(tempfile.gettempdir(), "canal_updater.bat")

    # ---- 鍏叡澶撮儴锛氱瓑寰呬富绋嬪簭閫€鍑?----
    bat_header = textwrap.dedent(f"""\
        @echo off
        chcp 65001 >nul
        title 姝ｅ湪鏇存柊 {APP_NAME_EN} ...
        echo.
        echo ============================================
        echo   姝ｅ湪鏇存柊锛岃鍕垮叧闂绐楀彛...
        echo ============================================
        echo.
        echo [姝ラ 1] 绛夊緟绋嬪簭閫€鍑?..
        set /a count=0
        :WAIT_LOOP
        tasklist /FI "PID eq %PARENT_PID%" 2>nul | find /i "{exe_name}" >nul
        if not errorlevel 1 (
            timeout /t 1 /nobreak >nul
            set /a count+=1
            if %count% lss 30 goto WAIT_LOOP
        )
        timeout /t 2 /nobreak >nul
    """)

    # ---- 鍏叡灏鹃儴锛氬惎鍔?+ 娓呯悊 ----
    bat_footer = textwrap.dedent(f"""\
        echo [瀹屾垚] 鍚姩鏂扮増鏈?..
        if exist "{app_dir}\\{exe_name}" (
            start "" "{app_dir}\\{exe_name}"
        ) else (
            echo [閿欒] 鏈壘鍒?{exe_name}锛岃鎵嬪姩鍚姩銆?            pause
        )
        del /f /q "{zip_path}" 2>nul
        echo.
        echo 鏇存柊瀹屾垚锛佹绐楀彛灏嗗湪 3 绉掑悗鍏抽棴銆?        timeout /t 3 /nobreak >nul
        del /f /q "%~f0" 2>nul
    """)

    if is_patch:
        # ---- 琛ヤ竵妯″紡锛氱洿鎺ヨ鐩栧彉鍖栨枃浠讹紝涓嶅仛鍏ㄩ噺澶囦唤 ----
        bat_body = textwrap.dedent(f"""\
            echo [姝ラ 2] 瑙ｅ帇澧為噺琛ヤ竵鍖?..
            powershell -NoProfile -Command ^
                "Expand-Archive -Path '{zip_path}' -DestinationPath '{app_dir}\\__patch_temp__' -Force"
            echo [姝ラ 3] 瑕嗙洊鍙樺寲鏂囦欢...
            xcopy /s /e /y "{app_dir}\\__patch_temp__\\*" "{app_dir}\\" >nul 2>&1
            if exist "{app_dir}\\__patch_temp__\\patch_manifest.json" (
                echo [姝ラ 4] 娓呯悊宸茬Щ闄ょ殑鏂囦欢...
                powershell -NoProfile -Command ^
                    "$m = Get-Content '{app_dir}\\__patch_temp__\\patch_manifest.json' | ConvertFrom-Json; ^
                     foreach ($f in $m.deleted) {{ $p = Join-Path '{app_dir}' $f; if (Test-Path $p) {{ Remove-Item $p -Force }} }}"
            )
            rmdir /s /q "{app_dir}\\__patch_temp__" 2>nul
            del /f /q "{app_dir}\\patch_manifest.json" 2>nul
        """)
    else:
        # ---- 鍏ㄩ噺妯″紡锛氬浠?+ 瑙ｅ帇瑕嗙洊 ----
        bat_body = textwrap.dedent(f"""\
            echo [姝ラ 2] 澶囦唤鏃х増鏈?..
            if exist "{app_dir}\\_backup" (
                rmdir /s /q "{app_dir}\\_backup" 2>nul
            )
            mkdir "{app_dir}\\_backup" 2>nul
            for %%F in ("{app_dir}\\*") do (
                if /i not "%%~nxF"=="_backup" (
                    if /i not "%%~xF"==".lic" (
                        move /y "%%F" "{app_dir}\\_backup\\" >nul 2>&1
                    )
                )
            )
            for /d %%D in ("{app_dir}\\*") do (
                if /i not "%%~nxD"=="_backup" (
                    move /y "%%D" "{app_dir}\\_backup\\" >nul 2>&1
                )
            )
            echo [姝ラ 3] 瑙ｅ帇鏂扮増鏈?..
            powershell -NoProfile -Command ^
                "Expand-Archive -Path '{zip_path}' -DestinationPath '{app_dir}\\__temp_extract__' -Force"
            for /d %%D in ("{app_dir}\\__temp_extract__\\*") do (
                xcopy /s /e /y "%%D\\*" "{app_dir}\\" >nul 2>&1
            )
            rmdir /s /q "{app_dir}\\__temp_extract__" 2>nul
            if exist "{app_dir}\\_backup\\*.lic" (
                copy /y "{app_dir}\\_backup\\*.lic" "{app_dir}\\" >nul 2>&1
            )
        """)

    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_header + bat_body + bat_footer)

    return bat_path


def launch_updater_and_exit(bat_path: str):
    """鍚姩鏇存柊鑴氭湰骞堕€€鍑哄綋鍓嶇▼搴?"""
    import subprocess

    pid = os.getpid()
    # 璁剧疆鐜鍙橀噺浼犻€掑綋鍓?PID 缁?bat 鑴氭湰
    env = os.environ.copy()
    env["PARENT_PID"] = str(pid)

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    # 閫€鍑轰富绋嬪簭
    sys.exit(0)



