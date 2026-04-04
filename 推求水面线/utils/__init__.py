# -*- coding: utf-8 -*-
"""工具模块"""

from .excel_io import ExcelIO
from .siphon_extractor import SiphonDataExtractor, SiphonGroup

__all__ = ['ExcelIO', 'SiphonDataExtractor', 'SiphonGroup']
"""推求水面线 utils 包初始化与打包导入兼容处理。"""

import sys


_project_utils_package = sys.modules.get(__name__)
_current_top_level_utils = sys.modules.get("utils")

# 打包环境里可能先加载到其他同名 utils 包，这里将顶层 utils 显式指回项目自带实现。
if _project_utils_package is not None and _current_top_level_utils is not _project_utils_package:
    if _current_top_level_utils is not None:
        for module_name in list(sys.modules):
            if module_name == "utils" or module_name.startswith("utils."):
                sys.modules.pop(module_name, None)
    sys.modules["utils"] = _project_utils_package
