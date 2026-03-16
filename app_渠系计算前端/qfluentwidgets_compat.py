# -*- coding: utf-8 -*-
"""QFluentWidgets 导入兼容层。

在部分 Windows 环境中，darkdetect.theme()/listener() 可能在导入阶段阻塞，
从而导致 qfluentwidgets 以及主程序启动卡住。这里提供一个轻量超时兜底：
探测超时后回退为浅色主题，并禁用系统主题监听。
"""

import os
import sys
import threading
import types
from typing import Any, Callable, Optional


_PATCH_FLAG = "_v1_darkdetect_guard_installed"
_DEFAULT_TIMEOUT_SECONDS = 1.0
_DEFAULT_FALLBACK_THEME = "Light"


def _read_timeout_seconds() -> float:
    raw = os.environ.get("V1_DARKDETECT_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT_SECONDS

    try:
        timeout = float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS

    return timeout if timeout > 0 else _DEFAULT_TIMEOUT_SECONDS


def _run_with_timeout(
    func: Callable[..., Any],
    *args: Any,
    timeout_seconds: float,
    fallback: Any,
    **kwargs: Any,
) -> Any:
    result: dict[str, Any] = {"value": fallback}
    done = threading.Event()

    def _target() -> None:
        try:
            result["value"] = func(*args, **kwargs)
        except Exception:
            result["value"] = fallback
        finally:
            done.set()

    threading.Thread(
        target=_target,
        name="darkdetect-guard",
        daemon=True,
    ).start()
    done.wait(timeout_seconds)
    return result["value"] if done.is_set() else fallback


def ensure_qfluentwidgets_compat(
    *,
    timeout_seconds: Optional[float] = None,
    fallback_theme: str = _DEFAULT_FALLBACK_THEME,
) -> None:
    """为 qfluentwidgets 安装 darkdetect 超时保护。"""
    darkdetect = sys.modules.get("darkdetect")
    if darkdetect is None:
        darkdetect = types.ModuleType("darkdetect")
        sys.modules["darkdetect"] = darkdetect
    elif getattr(darkdetect, _PATCH_FLAG, False):
        return

    timeout = timeout_seconds if timeout_seconds is not None else _read_timeout_seconds()
    timeout = timeout if timeout > 0 else _DEFAULT_TIMEOUT_SECONDS

    original_theme = getattr(darkdetect, "theme", None)
    if callable(original_theme):
        def _safe_theme() -> Any:
            return _run_with_timeout(
                original_theme,
                timeout_seconds=timeout,
                fallback=fallback_theme,
            )

        darkdetect.theme = _safe_theme
    else:
        darkdetect.theme = lambda: fallback_theme

    original_listener = getattr(darkdetect, "listener", None)
    if callable(original_listener):
        def _safe_listener(callback: Callable[..., Any]) -> Any:
            return _run_with_timeout(
                original_listener,
                callback,
                timeout_seconds=timeout,
                fallback=None,
            )

        darkdetect.listener = _safe_listener
    else:
        darkdetect.listener = lambda callback: None

    darkdetect.isDark = lambda: str(darkdetect.theme()).lower() == "dark"
    darkdetect.isLight = lambda: not darkdetect.isDark()
    darkdetect.__all__ = ["theme", "listener", "isDark", "isLight"]

    setattr(darkdetect, _PATCH_FLAG, True)
