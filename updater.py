# -*- coding: utf-8 -*-
"""
搴旂敤鍐呰嚜鍔ㄦ洿鏂版ā鍧?
鍔熻兘锛?1. 浼樺厛浠庡眬鍩熺綉鍏变韩鏂囦欢澶硅幏鍙栫増鏈俊鎭紙鏃犻渶澶栫綉锛?2. 灞€鍩熺綉涓嶅彲鐢ㄦ椂锛屽洖閫€鍒?GitHub Gist
3. 浼樺厛涓嬭浇澧為噺琛ヤ竵鍖咃紙閫氬父 <10MB锛夛紝澶辫触鏃跺洖閫€鍒板叏閲忓寘
4. 閫氳繃 .bat 鑴氭湰瀹炵幇"鍏抽棴鏃х▼搴?鈫?瑕嗙洊鏂囦欢 鈫?鍚姩鏂扮▼搴?

鏇存柊婧愪紭鍏堢骇锛氬眬鍩熺綉鍏变韩 > GitHub Gist
涓嬭浇浼樺厛绾э細  琛ヤ竵鍖?> 鍏ㄩ噺鍖?
杩滅▼鐗堟湰娓呭崟鏍煎紡锛坴ersion.json锛夛細
{
    "latest_version": "1.0.3",
    "download_url": "https://github.com/.../CanalHydraulicCalc-V1.0.3.zip",
    "patch_url": "https://github.com/.../CanalHydraulicCalc-V1.0.3-patch.zip",
    "changelog": "- 淇xxx\\n- 鏂板xxx",
    "release_date": "2026-03-01",
    "min_version": "1.0.0",
    "file_size_mb": 286.5,
    "patch_size_mb": 3.2,
    "patch_base_version": "1.0.2"
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
)

_CHECK_TIMEOUT = 8  # 妫€鏌ユ洿鏂拌秴鏃讹紙绉掞級


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
    """浠庤繙绋嬬増鏈竻鍗曡В鏋愬嚭鐨勬洿鏂颁俊鎭?"""

    def __init__(self, data: dict):
        self.latest_version: str = data.get("latest_version", "0.0.0")
        self.download_url: str = data.get("download_url", "")
        self.patch_url: str = data.get("patch_url", "")
        self.patches: dict = data.get("patches", {}) or {}
        self.source: str = data.get("source", "")
        self.changelog: str = data.get("changelog", "")
        self.release_date: str = data.get("release_date", "")
        self.min_version: str = data.get("min_version", "0.0.0")
        self.file_size_mb: float = data.get("file_size_mb", 0)
        self.patch_size_mb: float = data.get("patch_size_mb", 0)
        self.patch_base_version: str = data.get("patch_base_version", "")
        self._select_patch_for_current()

    def _select_patch_for_current(self):
        """Prefer multi-base patch metadata; fallback to legacy single patch fields."""
        if not isinstance(self.patches, dict):
            return

        patch_item = self.patches.get(APP_VERSION)
        if isinstance(patch_item, dict):
            url = str(patch_item.get("url", "")).strip()
            size_mb = patch_item.get("size_mb", 0)
        elif isinstance(patch_item, str):
            url = patch_item.strip()
            size_mb = 0
        else:
            return

        if not url:
            return

        self.patch_url = url
        self.patch_base_version = APP_VERSION
        try:
            self.patch_size_mb = float(size_mb or 0)
        except (TypeError, ValueError):
            self.patch_size_mb = 0

    @property
    def has_update(self) -> bool:
        return is_newer(self.latest_version)

    @property
    def is_forced(self) -> bool:
        """褰撳墠鐗堟湰浣庝簬鏈€浣庤姹傜増鏈椂锛屽己鍒舵洿鏂?"""
        return _parse_version(APP_VERSION) < _parse_version(self.min_version)

    @property
    def has_patch(self) -> bool:
        """鏄惁鎻愪緵浜嗗閲忚ˉ涓佸寘"""
        return bool(self.patch_url)

    @property
    def can_use_patch(self) -> bool:
        """褰撳墠鐗堟湰鏄惁鍙互浣跨敤澧為噺琛ヤ竵锛堥渶鍖归厤鍩虹嚎鐗堟湰锛?"""
        if not self.has_patch:
            return False
        if not self.patch_base_version:
            return True
        return _parse_version(APP_VERSION) == _parse_version(self.patch_base_version)


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
    """浠?HTTP URL 涓嬭浇 zip锛堟敮鎸佸绾跨▼鍒嗘骞跺彂锛?"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

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

    # 骞跺彂涓嬭浇
    try:
        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = []
            for i, (start, end) in enumerate(segments):
                fut = pool.submit(
                    _download_segment, url, start, end, dest_path,
                    progress_arr, i,
                )
                futures.append(fut)

            for fut in as_completed(futures):
                fut.result()  # 鎶涘嚭寮傚父锛堝鏈夛級
    except Exception:
        # 涓嬭浇澶辫触锛氭竻鐞嗘畫鐣欐枃浠讹紝閬垮厤鐣欎笅涓嶅畬鏁寸殑 zip
        try:
            os.remove(dest_path)
        except OSError:
            pass
        raise
    finally:
        stop_event.set()
        monitor.join(timeout=1)

    # 纭繚鏈€鍚庝竴娆¤繘搴︿负 100%
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
    """
    _ = source
    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="canal_update_")

    return _download_from_url(url, dest_dir, progress_callback)

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



