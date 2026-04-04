# -*- coding: utf-8 -*-
"""推求水面线 utils 顶层别名回归测试。"""

import importlib
import importlib.machinery
import sys
import types


def test_namespace_utils_import_overrides_shadowed_top_level_package(monkeypatch, tmp_path):
    """命名空间包导入后，应把顶层 utils 指回项目自带实现。"""
    shadow_utils = types.ModuleType("utils")
    shadow_spec = importlib.machinery.ModuleSpec("utils", loader=None, is_package=True)
    shadow_spec.submodule_search_locations = [str(tmp_path)]
    shadow_utils.__spec__ = shadow_spec
    shadow_utils.__path__ = [str(tmp_path)]

    monkeypatch.setitem(sys.modules, "utils", shadow_utils)
    sys.modules.pop("推求水面线.utils", None)

    project_utils = importlib.import_module("推求水面线.utils")

    assert sys.modules["utils"] is project_utils
    assert project_utils.__name__ == "推求水面线.utils"
