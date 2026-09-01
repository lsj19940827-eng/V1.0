# -*- coding: utf-8 -*-
"""PyInstaller 最早期运行钩子：禁止 Python platform 在主程序前触发 WMI。"""

import platform as _platform


def _disabled_wmi_query(*_args, **_kwargs):
    """让 platform 立即走非 WMI 回退路径，避免部分 Windows 机器启动卡死。"""
    raise OSError("Windows WMI query disabled before PyInstaller runtime hooks")


_platform._wmi_query = _disabled_wmi_query
if hasattr(_platform, "_wmi"):
    _platform._wmi = None
if hasattr(_platform, "_uname_cache"):
    _platform._uname_cache = None
