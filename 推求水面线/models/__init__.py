# -*- coding: utf-8 -*-
"""数据模型模块；新旧导入入口共享同一组枚举和节点类型。"""

import importlib
from pathlib import Path
import sys


_CANONICAL_PACKAGE = "推求水面线.models"
_LEGACY_PACKAGE = "models"


def _load_shared_module(name):
    """无论哪个入口先加载，都在导入依赖前建立另一入口的别名。"""
    canonical_name = f"{_CANONICAL_PACKAGE}.{name}"
    legacy_name = f"{_LEGACY_PACKAGE}.{name}"
    existing = sys.modules.get(canonical_name) or sys.modules.get(legacy_name)
    if existing is None:
        existing = importlib.import_module(f"{__name__}.{name}")
    else:
        expected = Path(__file__).with_name(f"{name}.py").resolve()
        source = getattr(existing, "__file__", None)
        if source and Path(source).resolve() != expected:
            raise ImportError(f"水面线数据模型与已加载的同名模块冲突: {name}")
    sys.modules[canonical_name] = existing
    sys.modules[legacy_name] = existing
    globals()[name] = existing
    return existing


# 旧脚本先导入 models 时也必须注册正式包名，否则之后导入节点编解码器
# 会重新创建枚举，使已构造节点的进出口标识不能被下游提取器识别。
_package = sys.modules[__name__]
sys.modules[_CANONICAL_PACKAGE] = _package
sys.modules[_LEGACY_PACKAGE] = _package
setattr(importlib.import_module("推求水面线"), "models", _package)
_enums = _load_shared_module("enums")
_load_shared_module("pressure_pipe_override")
_data_models = _load_shared_module("data_models")
_load_shared_module("profile_state")

StructureType, InOutType = _enums.StructureType, _enums.InOutType
ChannelNode = _data_models.ChannelNode
ProjectSettings = _data_models.ProjectSettings
OpenChannelParams = _data_models.OpenChannelParams

__all__ = ['StructureType', 'InOutType', 'ChannelNode', 'ProjectSettings', 'OpenChannelParams']
