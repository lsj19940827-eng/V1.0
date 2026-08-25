# -*- coding: utf-8 -*-
"""水面线核心计算引擎加载失败诊断，供面板提示和本机日志复用。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import traceback
from typing import Optional

from version import APP_NAME_EN, APP_VERSION


CORE_ENGINE_LOG_NAME = "water_profile_core_engine.log"


@dataclass(frozen=True)
class CoreEngineLoadFailure:
    """保存一次核心计算引擎导入失败的可展示信息。"""

    exception_type: str
    message: str
    missing_module: str
    timestamp: str
    log_path: str
    log_write_error: str
    diagnostic_text: str

    def reason_text(self) -> str:
        """返回适合直接展示给用户的简短原因。"""
        if self.missing_module:
            return f"缺少或无法加载模块：{self.missing_module}"
        if self.message:
            return f"{self.exception_type}：{self.message}"
        return self.exception_type or "未知导入错误"


def _resolve_default_log_dir() -> Path:
    """返回与安装目录无关、普通用户可写的应用日志目录。"""
    base_dir = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base_dir) / APP_NAME_EN / "logs"


def _safe_current_directory() -> str:
    """读取当前目录；目录已失效时返回诊断文字而不是继续抛错。"""
    try:
        return os.getcwd()
    except OSError as error:
        return f"无法读取当前目录：{type(error).__name__}: {error}"


def _should_skip_default_log_write(log_dir: Optional[Path]) -> bool:
    """测试进程未指定临时目录时不写真实用户日志。"""
    return log_dir is None and "pytest" in sys.modules


def _build_diagnostic_text(
    exc: BaseException,
    *,
    timestamp: str,
    traceback_text: str,
) -> str:
    """生成可写入日志、也可从界面复制的完整诊断文本。"""
    missing_module = str(getattr(exc, "name", "") or "").strip()
    meipass = str(getattr(sys, "_MEIPASS", "") or "").strip()
    lines = [
        "水面线核心计算引擎加载失败",
        f"时间：{timestamp}",
        f"软件版本：{APP_VERSION}",
        f"异常类型：{type(exc).__name__}",
        f"异常信息：{str(exc).strip() or '未提供'}",
        f"缺失模块：{missing_module or '未识别'}",
        f"是否打包运行：{bool(getattr(sys, 'frozen', False))}",
        f"程序入口：{sys.executable}",
        f"运行目录：{_safe_current_directory()}",
        f"打包资源目录：{meipass or '非打包运行或未提供'}",
        "",
        "完整异常：",
        traceback_text.strip() or "未取得完整异常。",
    ]
    return "\n".join(lines)


def record_core_engine_import_failure(
    exc: BaseException,
    *,
    log_dir: Optional[Path] = None,
    traceback_text: str = "",
) -> CoreEngineLoadFailure:
    """记录导入失败；即使日志目录不可写，也保证返回可展示的诊断对象。"""
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    if not traceback_text:
        traceback_text = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
    diagnostic_text = _build_diagnostic_text(
        exc,
        timestamp=timestamp,
        traceback_text=traceback_text,
    )

    log_path = ""
    log_write_error = ""
    if not _should_skip_default_log_write(log_dir):
        target_dir = Path(log_dir) if log_dir is not None else _resolve_default_log_dir()
        target_path = target_dir / CORE_ENGINE_LOG_NAME
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            with target_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(diagnostic_text)
                stream.write("\n\n")
            log_path = str(target_path)
        except (OSError, ValueError) as write_error:
            log_write_error = f"{type(write_error).__name__}: {write_error}"

    return CoreEngineLoadFailure(
        exception_type=type(exc).__name__,
        message=str(exc).strip(),
        missing_module=str(getattr(exc, "name", "") or "").strip(),
        timestamp=timestamp,
        log_path=log_path,
        log_write_error=log_write_error,
        diagnostic_text=diagnostic_text,
    )


def build_core_engine_user_message(
    failure: Optional[CoreEngineLoadFailure],
    *,
    action_name: str = "当前操作",
) -> str:
    """生成故障窗口顶部的简明说明和可执行恢复建议。"""
    action_text = str(action_name or "当前操作").strip()
    if failure is None:
        reason = "未取得具体导入异常"
        log_hint = "本次未生成诊断日志。"
    else:
        reason = failure.reason_text()
        if failure.log_path:
            log_hint = f"诊断日志：{failure.log_path}"
        elif failure.log_write_error:
            log_hint = f"诊断日志写入失败：{failure.log_write_error}"
        else:
            log_hint = "本次未生成诊断日志。"

    return (
        f"水面线核心计算引擎未能加载，无法{action_text}。\n\n"
        f"原因：{reason}\n"
        f"{log_hint}\n\n"
        "建议先关闭软件，使用当前版本的完整安装包覆盖安装后重试；"
        "如果仍然失败，请把下方可复制诊断信息或日志文件发给开发人员。"
    )


def build_core_engine_copyable_details(
    failure: Optional[CoreEngineLoadFailure],
) -> str:
    """返回故障窗口中可直接复制的诊断信息。"""
    if failure is None:
        return (
            "水面线核心计算引擎未加载，但本次没有取得具体异常。\n"
            f"软件版本：{APP_VERSION}\n"
            f"程序入口：{sys.executable}"
        )
    details = failure.diagnostic_text
    if failure.log_path:
        details += f"\n\n诊断日志：{failure.log_path}"
    elif failure.log_write_error:
        details += f"\n\n诊断日志写入失败：{failure.log_write_error}"
    return details
