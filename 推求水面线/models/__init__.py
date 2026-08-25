# -*- coding: utf-8 -*-
"""数据模型模块"""

import sys

from .enums import StructureType, InOutType
from .data_models import ChannelNode, ProjectSettings, OpenChannelParams

# 兼容仍使用顶层 models.* 的旧脚本，同时保证类型对象不被重复加载。
if __name__.startswith("推求水面线."):
    sys.modules["models"] = sys.modules[__name__]
    sys.modules["models.enums"] = sys.modules[f"{__name__}.enums"]
    sys.modules["models.data_models"] = sys.modules[f"{__name__}.data_models"]

__all__ = ['StructureType', 'InOutType', 'ChannelNode', 'ProjectSettings', 'OpenChannelParams']
