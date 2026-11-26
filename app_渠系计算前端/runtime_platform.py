# -*- coding: utf-8 -*-
"""轻量运行环境保护，可在界面和外部库导入前使用。"""

import sys


_PLATFORM_WMI_GUARD_FLAG = "_v1_platform_wmi_guard_installed"


def ensure_safe_windows_platform_queries() -> None:
    """禁用 Python platform 的 Windows WMI 查询，避免第三方库导入时卡住。"""
    if not sys.platform.startswith("win"):
        return
    try:
        import platform as std_platform
    except Exception:
        return

    if getattr(std_platform, _PLATFORM_WMI_GUARD_FLAG, False):
        return

    def _disabled_wmi_query(*_args, **_kwargs):
        """让 platform 立即走非 WMI 回退路径。"""
        raise OSError("Windows WMI query disabled to avoid startup hang")

    try:
        std_platform._wmi_query = _disabled_wmi_query
        if hasattr(std_platform, "_wmi"):
            std_platform._wmi = None
        if hasattr(std_platform, "_uname_cache"):
            std_platform._uname_cache = None
        setattr(std_platform, _PLATFORM_WMI_GUARD_FLAG, True)
    except Exception:
        pass
