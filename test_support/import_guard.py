"""隔离历史界面测试中的导入替身及间接导入缓存。"""

from contextlib import contextmanager
from functools import wraps
import sys
from types import ModuleType


_ROOTS = (
    'utils', 'models', 'core', 'shared', '推求水面线', 'PySide6', 'qfluentwidgets',
    'app_渠系计算前端', '明渠设计', '渡槽设计', '隧洞设计', '矩形暗涵设计',
)


def _guarded(name):
    return any(name == root or name.startswith(root + '.') for root in _ROOTS)


def _native_qt_module(name, module):
    """真实 Qt 扩展含不可逆的延迟类型注册，不能清空属性或卸载缓存。"""
    return (name == 'PySide6' or name.startswith('PySide6.')) and bool(getattr(module, '__file__', None))


@contextmanager
def import_state_guard():
    """恢复模块映射、旧包对象属性与搜索路径，包含替身环境产生的新缓存。"""
    before = dict(sys.modules)
    attributes = {
        name: dict(vars(module)) for name, module in before.items()
        if _guarded(name) and isinstance(module, ModuleType) and not _native_qt_module(name, module)
    }
    search_path = list(sys.path)
    try:
        yield
    finally:
        # 正常依赖的全局缓存保留；工程和界面命名空间的新增模块须清除。
        for name in list(sys.modules):
            if name not in before and _guarded(name) and not _native_qt_module(name, sys.modules[name]):
                sys.modules.pop(name, None)
        for name, module in before.items():
            if sys.modules.get(name) is not module:
                sys.modules[name] = module
        # 只恢复 sys.modules 会遗漏原地 setattr 的包属性，例如 utils.xxx。
        for name, old_values in attributes.items():
            namespace = vars(before[name])
            for key in list(namespace):
                if key not in old_values:
                    namespace.pop(key, None)
            namespace.update(old_values)
        sys.path[:] = search_path


def isolated_imports(function):
    """给导入助手或含运行时替身的测试提供同一隔离边界。"""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with import_state_guard():
            return function(*args, **kwargs)
    return wrapped
