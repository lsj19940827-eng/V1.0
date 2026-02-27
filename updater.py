# -*- coding: utf-8 -*-
"""
应用内自动更新模块

功能：
1. 优先从局域网共享文件夹获取版本信息（无需外网）
2. 局域网不可用时，回退到 GitHub Gist
3. 优先下载增量补丁包（通常 <10MB），失败时回退到全量包
4. 通过 .bat 脚本实现"关闭旧程序 → 覆盖文件 → 启动新程序"

更新源优先级：局域网共享 > GitHub Gist
下载优先级：  补丁包 > 全量包

远程版本清单格式（version.json）：
{
    "latest_version": "1.0.3",
    "download_url": "https://github.com/.../CanalHydraulicCalc-V1.0.3.zip",
    "patch_url": "https://github.com/.../CanalHydraulicCalc-V1.0.3-patch.zip",
    "changelog": "- 修复xxx\\n- 新增xxx",
    "release_date": "2026-03-01",
    "min_version": "1.0.0",
    "file_size_mb": 286.5,
    "patch_size_mb": 3.2
}
"""

import json
import os
import shutil
import sys
import tempfile
import textwrap
import urllib.request
import urllib.error
from typing import Optional, Callable

from version import APP_VERSION, APP_NAME_EN
from repo_config import (
    GITHUB_VERSION_URL as _GITHUB_VERSION_URL,
    GITEE_VERSION_URL as _GITEE_VERSION_URL,
    LAN_UPDATE_DIR as _LAN_UPDATE_DIR,
)

_CHECK_TIMEOUT = 8  # 检查更新超时（秒）


# ============================================================
# 版本比较
# ============================================================
def _parse_version(v: str) -> tuple:
    """将 '1.0.2' 解析为 (1, 0, 2) 以便比较"""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def is_newer(remote_ver: str, local_ver: str = APP_VERSION) -> bool:
    """远程版本是否比本地版本更新"""
    return _parse_version(remote_ver) > _parse_version(local_ver)


# ============================================================
# 检查更新
# ============================================================
class UpdateInfo:
    """从远程版本清单解析出的更新信息"""

    def __init__(self, data: dict):
        self.latest_version: str = data.get("latest_version", "0.0.0")
        self.download_url: str = data.get("download_url", "")
        self.patch_url: str = data.get("patch_url", "")
        self.changelog: str = data.get("changelog", "")
        self.release_date: str = data.get("release_date", "")
        self.min_version: str = data.get("min_version", "0.0.0")
        self.file_size_mb: float = data.get("file_size_mb", 0)
        self.patch_size_mb: float = data.get("patch_size_mb", 0)

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


def _check_lan() -> Optional[UpdateInfo]:
    """从局域网共享文件夹读取版本信息"""
    try:
        manifest_path = os.path.join(_LAN_UPDATE_DIR, "version.json")
        if not os.path.exists(manifest_path):
            return None
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        info = UpdateInfo(data)
        info.source = "lan"
        return info
    except Exception:
        return None


def _check_remote(url: str, source_name: str) -> Optional[UpdateInfo]:
    """从远程 URL 读取版本信息"""
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
    检查是否有新版本。

    优先级：局域网共享 → Gitee（国内快） → GitHub（外网）
    全部失败时静默返回 None。

    Returns:
        UpdateInfo  —— 成功获取到远程信息（.source 标记来源）
        None        —— 全部失败
    """
    # 优先局域网（速度快、无需外网）
    info = _check_lan()
    if info is not None:
        return info
    # Gitee（国内快，不需要翻墙）
    info = _check_remote(_GITEE_VERSION_URL, "gitee")
    if info is not None:
        return info
    # GitHub（外网回退）
    return _check_remote(_GITHUB_VERSION_URL, "github")


# ============================================================
# 下载更新包
# ============================================================
def _download_from_lan(
    filename: str,
    dest_dir: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Optional[str]:
    """从局域网共享文件夹复制 zip（速度极快）"""
    try:
        src = os.path.join(_LAN_UPDATE_DIR, filename)
        if not os.path.exists(src):
            return None
        dest = os.path.join(dest_dir, filename)
        total = os.path.getsize(src)
        copied = 0
        chunk_size = 256 * 1024  # 256KB
        with open(src, "rb") as fin, open(dest, "wb") as fout:
            while True:
                chunk = fin.read(chunk_size)
                if not chunk:
                    break
                fout.write(chunk)
                copied += len(chunk)
                if progress_callback:
                    progress_callback(copied, total)
        return dest
    except Exception:
        return None


def _download_from_url(
    url: str,
    dest_dir: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """从 HTTP URL 下载 zip"""
    filename = url.rsplit("/", 1)[-1] or f"{APP_NAME_EN}-update.zip"
    dest_path = os.path.join(dest_dir, filename)

    req = urllib.request.Request(
        url, headers={"User-Agent": f"{APP_NAME_EN}/{APP_VERSION}"}
    )
    resp = urllib.request.urlopen(req, timeout=60)
    total = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    chunk_size = 64 * 1024  # 64KB

    with open(dest_path, "wb") as f:
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
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
    下载更新 zip 到本地临时目录。

    如果 source == 'lan'，优先从局域网共享复制（极快）。
    局域网失败或 source != 'lan' 时，从 URL 下载。

    Args:
        url: 下载地址（HTTP URL）
        dest_dir: 保存目录（默认系统临时目录）
        progress_callback: 回调 (downloaded_bytes, total_bytes)
        source: 更新源标记（'lan' 或 'github'）

    Returns:
        下载完成的文件绝对路径
    """
    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="canal_update_")

    # 局域网源：直接从共享文件夹复制
    if source == "lan":
        filename = url.rsplit("/", 1)[-1] if "/" in url else url
        if not filename:
            filename = f"{APP_NAME_EN}-update.zip"
        result = _download_from_lan(filename, dest_dir, progress_callback)
        if result:
            return result
        # 局域网复制失败，回退到 URL 下载

    return _download_from_url(url, dest_dir, progress_callback)


# ============================================================
# 应用更新（生成 .bat 脚本并执行）
# ============================================================
def _get_app_dir() -> str:
    """获取当前应用程序所在目录"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后
        return os.path.dirname(sys.executable)
    else:
        # 开发环境
        return os.path.dirname(os.path.abspath(__file__))


def apply_update(zip_path: str, is_patch: bool = False) -> str:
    """
    生成更新用 .bat 脚本。

    全量模式 (is_patch=False): 备份全部旧文件 -> 解压新 zip 覆盖 -> 启动
    补丁模式 (is_patch=True):  解压补丁 zip 直接覆盖变化文件 -> 删除已移除文件 -> 启动

    Args:
        zip_path: 已下载的 zip 文件路径
        is_patch: 是否为增量补丁包

    Returns:
        生成的 bat 文件路径（调用方应在执行后退出主程序）
    """
    app_dir = _get_app_dir()
    exe_name = f"{APP_NAME_EN}.exe"
    bat_path = os.path.join(tempfile.gettempdir(), "canal_updater.bat")

    # ---- 公共头部：等待主程序退出 ----
    bat_header = textwrap.dedent(f"""\
        @echo off
        chcp 65001 >nul
        title 正在更新 {APP_NAME_EN} ...
        echo.
        echo ============================================
        echo   正在更新，请勿关闭此窗口...
        echo ============================================
        echo.
        echo [步骤 1] 等待程序退出...
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

    # ---- 公共尾部：启动 + 清理 ----
    bat_footer = textwrap.dedent(f"""\
        echo [完成] 启动新版本...
        if exist "{app_dir}\\{exe_name}" (
            start "" "{app_dir}\\{exe_name}"
        ) else (
            echo [错误] 未找到 {exe_name}，请手动启动。
            pause
        )
        del /f /q "{zip_path}" 2>nul
        echo.
        echo 更新完成！此窗口将在 3 秒后关闭。
        timeout /t 3 /nobreak >nul
        del /f /q "%~f0" 2>nul
    """)

    if is_patch:
        # ---- 补丁模式：直接覆盖变化文件，不做全量备份 ----
        bat_body = textwrap.dedent(f"""\
            echo [步骤 2] 解压增量补丁包...
            powershell -NoProfile -Command ^
                "Expand-Archive -Path '{zip_path}' -DestinationPath '{app_dir}\\__patch_temp__' -Force"
            echo [步骤 3] 覆盖变化文件...
            xcopy /s /e /y "{app_dir}\\__patch_temp__\\*" "{app_dir}\\" >nul 2>&1
            if exist "{app_dir}\\__patch_temp__\\patch_manifest.json" (
                echo [步骤 4] 清理已移除的文件...
                powershell -NoProfile -Command ^
                    "$m = Get-Content '{app_dir}\\__patch_temp__\\patch_manifest.json' | ConvertFrom-Json; ^
                     foreach ($f in $m.deleted) {{ $p = Join-Path '{app_dir}' $f; if (Test-Path $p) {{ Remove-Item $p -Force }} }}"
            )
            rmdir /s /q "{app_dir}\\__patch_temp__" 2>nul
            del /f /q "{app_dir}\\patch_manifest.json" 2>nul
        """)
    else:
        # ---- 全量模式：备份 + 解压覆盖 ----
        bat_body = textwrap.dedent(f"""\
            echo [步骤 2] 备份旧版本...
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
            echo [步骤 3] 解压新版本...
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
    """启动更新脚本并退出当前程序"""
    import subprocess

    pid = os.getpid()
    # 设置环境变量传递当前 PID 给 bat 脚本
    env = os.environ.copy()
    env["PARENT_PID"] = str(pid)

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    # 退出主程序
    sys.exit(0)
