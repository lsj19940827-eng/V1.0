# -*- coding: utf-8 -*-
"""倒虹吸领域包；兼容旧脚本的裸模块导入并统一枚举、模型身份。"""

import importlib
from pathlib import Path
import sys


def _load_compatible_module(name):
    """仅复用本目录的旧模块，禁止误接入外部同名模块。"""
    qualified_name = f"{__name__}.{name}"
    existing = sys.modules.get(name)
    if existing is not None:
        expected_path = Path(__file__).with_name(f"{name}.py").resolve()
        existing_path = getattr(existing, "__file__", None)
        resolved_path = Path(existing_path).resolve() if existing_path else None
        matches_source = resolved_path == expected_path
        # PyInstaller 的旧裸模块可能位于解包根目录，正式模块位于子包目录。
        # 两者来自同一构建；仅允许本次解包目录下对应文件名的既有模块。
        bundle_root = getattr(sys, "_MEIPASS", None)
        matches_legacy_bundle = bool(
            getattr(sys, "frozen", False) and bundle_root and resolved_path
            and resolved_path.parent == Path(bundle_root).resolve()
            and resolved_path.stem == name
            and resolved_path.suffix in (".py", ".pyc")
        )
        if not matches_source and not matches_legacy_bundle:
            raise ImportError(f"倒虹吸计算组件与已加载的同名模块冲突: {name}")
        sys.modules[qualified_name] = existing
        globals()[name] = existing
        return existing
    module = importlib.import_module(qualified_name)
    sys.modules[name] = module
    return module


for _name in ("arc_geometry", "siphon_models", "siphon_coefficients"):
    _load_compatible_module(_name)
