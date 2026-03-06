# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')

import ctypes
from ctypes import wintypes
from pathlib import Path


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", ctypes.c_uint),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004


def send_to_recycle_bin(path_str: str) -> bool:
    fileop = SHFILEOPSTRUCTW()
    fileop.hwnd = None
    fileop.wFunc = FO_DELETE
    fileop.pFrom = path_str + '\0'
    fileop.pTo = None
    fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
    return result == 0


base = Path.home() / "Desktop" / "V1.0"

targets_files = [
    # 一次性修复脚本
    "fix_example1.py",
    "fix_example2.py",
    "fix_panel.py",
    # 根目录散落的测试脚本
    "test_case_management.py",
    "test_example_data_enhancement.py",
    "test_pressure_pipe_ui.py",
    "test_siphon_example.py",
    "test_siphon_example_flag.py",
    "test_siphon_max_flow_loss.py",
    "test_siphon_ui_detail.py",
    # 开发调试脚本
    "manual_test_example_data.py",
    "audit_siphon.py",
    # 冗余的发版脚本（已整合到 tools/release.py）
    "update_gist_only.py",
    "upload_to_release.py",
    "create_release.py",
    # 日志文件
    "debug.log",
    str(Path("data") / "run_errors.log"),
    # 临时输出
    str(Path("tools") / "compare_result.txt"),
]

targets_dirs = [
    # 测试生成的临时数据
    str(Path("data") / "_test_auto_confirm"),
    str(Path("data") / "_test_unified_confirm"),
    # 构建产物（可随时重新生成）
    "dist",
    # 测试缓存
    ".pytest_cache",
]

ok_count = 0
skip_count = 0

for name in targets_files:
    p = base / name
    if p.exists():
        if send_to_recycle_bin(str(p)):
            print(f"[回收站] {name}")
            ok_count += 1
        else:
            print(f"[失败]   {name}")
    else:
        print(f"[跳过]   {name} (不存在)")
        skip_count += 1

for name in targets_dirs:
    p = base / name
    if p.exists():
        if send_to_recycle_bin(str(p)):
            print(f"[回收站] {name}/")
            ok_count += 1
        else:
            print(f"[失败]   {name}/")
    else:
        print(f"[跳过]   {name}/ (不存在)")
        skip_count += 1

print(f"\n完成: {ok_count} 个已移到回收站, {skip_count} 个跳过")
