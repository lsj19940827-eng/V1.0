"""水面线后台计算的数据边界，不依赖任何界面控件。"""

from dataclasses import dataclass
from typing import Any

from .calculator import WaterProfileCalculator


@dataclass
class ProfileCalculationResult:
    nodes: list
    settings: Any
    calculator: WaterProfileCalculator


def calculate_profile(nodes, settings, cancel_check=None):
    """接收调用方已经隔离的输入快照，取消在每个计算阶段生效。"""
    calculator = WaterProfileCalculator(settings)
    result = calculator.calculate_all(nodes, cancel_check=cancel_check)
    return ProfileCalculationResult(result, settings, calculator)
