# -*- coding: utf-8 -*-
"""打包器入口：在导入 PyInstaller 前应用 Windows 启动保护。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 子进程不继承父进程的平台补丁，须在自身依赖初始化前启用。
import tools.pyinstaller_runtime_wmi_guard  # noqa: E402,F401
from PyInstaller import isolated  # noqa: E402
from PyInstaller.__main__ import run  # noqa: E402


def _prepare_isolated_child():
    """依赖分析进程也须先应用平台保护，再执行包探测。"""
    import tools.pyinstaller_runtime_wmi_guard  # noqa: F401


_original_enter = isolated.Python.__enter__


def _guarded_enter(self):
    child = _original_enter(self)
    child.call(_prepare_isolated_child)
    return child


if __name__ == "__main__":
    isolated.Python.__enter__ = _guarded_enter
    run()
