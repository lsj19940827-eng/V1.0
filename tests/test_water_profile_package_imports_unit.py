# -*- coding: utf-8 -*-
"""验证推求水面线核心始终通过完整包命名空间加载。"""

import importlib


def test_water_profile_core_imports_from_qualified_package():
    """完整包导入不得退化到容易冲突的顶层 core 命名空间。"""
    core_package = importlib.import_module("推求水面线.core")
    adapter = importlib.import_module("推求水面线.core.spillway_steep_chute_adapter")

    assert core_package.WaterProfileCalculator.__module__ == "推求水面线.core.calculator"
    assert adapter.__package__ == "推求水面线.core"


def test_water_profile_panel_uses_qualified_core_imports():
    """面板源码必须保留完整包路径，避免冻结环境解析到同名包。"""
    panel = importlib.import_module("app_渠系计算前端.water_profile.panel")

    assert panel.CALCULATOR_AVAILABLE is True
    assert panel.CORE_ENGINE_LOAD_FAILURE is None
    assert panel.WaterProfileCalculator.__module__ == "推求水面线.core.calculator"
