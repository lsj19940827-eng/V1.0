"""导入替身隔离必须恢复已有对象属性，并清理未逐一列出的子模块。"""

import sys
from types import ModuleType

import pytest

from test_support.import_guard import import_state_guard


def test_guard_restores_parent_attributes_and_indirect_module_on_exception(monkeypatch):
    original = ModuleType('utils')
    child = ModuleType('utils.pressure_pipe_result_helpers')
    original.pressure_pipe_result_helpers = child
    monkeypatch.setitem(sys.modules, 'utils', original)
    monkeypatch.setitem(sys.modules, 'utils.pressure_pipe_result_helpers', child)
    missing = 'utils.test_indirect_cache'
    monkeypatch.delitem(sys.modules, missing, raising=False)
    with pytest.raises(RuntimeError):
        with import_state_guard():
            original.pressure_pipe_result_helpers = ModuleType('fake')
            original.new_attribute = 1
            sys.modules[missing] = ModuleType(missing)
            sys.path.insert(0, '仅测试路径')
            raise RuntimeError('模拟导入中断')
    assert sys.modules['utils'] is original
    assert original.pressure_pipe_result_helpers is child
    assert not hasattr(original, 'new_attribute')
    assert missing not in sys.modules
    assert '仅测试路径' not in sys.path


def test_guard_keeps_qt_lazy_native_types_available():
    """访问真实 Qt 延迟导出后不能删掉其属性，扩展不会重复注册这些类型。"""
    from PySide6 import QtWidgets
    with import_state_guard():
        widget_type = QtWidgets.QWidget
        view_type = QtWidgets.QColumnView
    assert QtWidgets.QWidget is widget_type
    assert QtWidgets.QColumnView is view_type
