# -*- coding: utf-8 -*-
"""核心计算模块"""

import sys

from .geometry_calc import GeometryCalculator
from .hydraulic_calc import HydraulicCalculator
from .calculator import WaterProfileCalculator

# 兼容仍使用顶层 core.* 的旧脚本，同时避免冻结环境重复创建同名包。
if __name__.startswith("推求水面线."):
    sys.modules["core"] = sys.modules[__name__]
    for _module_name in (
        "geometry_calc",
        "hydraulic_calc",
        "calculator",
        "pressure_pipe_calc",
        "spillway_steep_chute_adapter",
    ):
        _qualified_name = f"{__name__}.{_module_name}"
        if _qualified_name in sys.modules:
            sys.modules[f"core.{_module_name}"] = sys.modules[_qualified_name]

__all__ = ['GeometryCalculator', 'HydraulicCalculator', 'WaterProfileCalculator']
