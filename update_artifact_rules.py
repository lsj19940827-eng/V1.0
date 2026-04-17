# -*- coding: utf-8 -*-
"""在线更新相关的文件边界规则。

这个模块只负责回答两件事：
1. 哪些路径属于程序运行时会变化的用户数据，不应进入严格补丁校验。
2. 哪些路径在全量安装成功后也必须保留下来，避免覆盖用户本地数据。
"""

from __future__ import annotations

import fnmatch
import os

# 运行时会被程序持续改写的文件，不能拿来当补丁基线。
RUNTIME_ARTIFACT_PATTERNS = [
    "data/siphon_autosave.json",
    "_internal/data/siphon_autosave.json",
    "data/autosave/*",
    "_internal/data/autosave/*",
    "data/*_autosave.qxproj",
    "_internal/data/*_autosave.qxproj",
]

# 成功安装后也要保住的用户数据。
DEFAULT_PRESERVE_PATTERNS = [
    "*.lic",
    *RUNTIME_ARTIFACT_PATTERNS,
]


def normalize_relative_path(path: str) -> str:
    """统一相对路径格式，便于跨平台匹配。"""
    return (path or "").replace("\\", "/").lstrip("./")


def path_matches_patterns(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    """判断路径是否命中任一规则。"""
    normalized = normalize_relative_path(path)
    filename = os.path.basename(normalized)
    return any(
        fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(filename, pattern)
        for pattern in patterns
    )


def is_runtime_artifact(path: str) -> bool:
    """判断是否属于运行时文件。"""
    return path_matches_patterns(path, RUNTIME_ARTIFACT_PATTERNS)


def should_preserve_path(
    path: str,
    extra_patterns: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """判断路径是否需要在成功安装后保留。"""
    patterns = list(DEFAULT_PRESERVE_PATTERNS)
    if extra_patterns:
        patterns.extend(list(extra_patterns))
    return path_matches_patterns(path, patterns)
