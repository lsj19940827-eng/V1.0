# -*- coding: utf-8 -*-
"""调试输出工具。默认不打印，设置 APP_DEBUG=1 时启用。"""

import os


def _is_debug_enabled() -> bool:
    value = os.environ.get("APP_DEBUG", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def debug_print(*args, **kwargs) -> None:
    """仅在显式开启调试开关时输出调试信息。"""
    if _is_debug_enabled():
        print(*args, **kwargs)
