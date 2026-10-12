# -*- coding: utf-8 -*-
"""水面线轻量导入与按需 Excel 兼容入口的独立进程回归。"""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]

# 独立进程不继承主程序的启动防护，避免 pandas 查询 Windows WMI 时挂起。
_PROCESS_PRELUDE = """
import platform
import sys
if sys.platform.startswith('win'):
    def _disabled_wmi_query(*args, **kwargs):
        raise OSError('Windows WMI query disabled to avoid startup hang')
    platform._wmi_query = _disabled_wmi_query
    if hasattr(platform, '_wmi'):
        platform._wmi = None
    platform._uname_cache = None
"""


def _run_isolated(source, *arguments):
    """使用当前项目解释器及新导入状态，不在仓库内生成缓存或 Excel 文件。"""
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-B", "-c", _PROCESS_PRELUDE + textwrap.dedent(source),
         *(str(argument) for argument in arguments)],
        cwd=ROOT, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_numeric_and_utils_imports_do_not_attempt_excel_dependencies():
    """拦截导入尝试，防止 ExcelIO 吞掉依赖异常后形成假通过。"""
    _run_isolated("""
        import importlib
        import importlib.abc

        attempted = []
        class BlockExcelDependencies(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.', 1)[0] in {'pandas', 'openpyxl'}:
                    attempted.append(fullname)
                    raise AssertionError('轻量入口不应尝试导入 Excel 依赖: ' + fullname)

        sys.meta_path.insert(0, BlockExcelDependencies())
        from 推求水面线.utils.numeric_precision import format_input_number, station_millimetres
        package = importlib.import_module('推求水面线.utils')
        from 推求水面线.utils import SiphonDataExtractor, SiphonGroup

        assert format_input_number(0.123456789) == '0.123456789'
        assert station_millimetres(1234.5678) == 1234568
        assert importlib.import_module('utils') is package
        assert SiphonDataExtractor is package.SiphonDataExtractor
        assert SiphonGroup is package.SiphonGroup
        assert package.__all__ == ['ExcelIO', 'SiphonDataExtractor', 'SiphonGroup']
        assert 'ExcelIO' not in vars(package)
        assert not any(name.endswith('.utils.excel_io') or name == 'utils.excel_io'
                       for name in sys.modules)
        assert not attempted, attempted
        assert not any(name.split('.', 1)[0] in {'pandas', 'openpyxl'}
                       for name in sys.modules)
    """)


@pytest.mark.parametrize("first_entry", ["canonical", "legacy"])
def test_excel_export_keeps_class_identity_for_both_package_entries(first_entry):
    """建立正式包别名后，两个既有导出入口按任何访问次序得到同一真实类。"""
    _run_isolated("""
        import importlib
        package = importlib.import_module('推求水面线.utils')
        assert 'ExcelIO' not in vars(package)
        if sys.argv[1] == 'canonical':
            from 推求水面线.utils import ExcelIO as first
            from utils import ExcelIO as second
        else:
            from utils import ExcelIO as first
            from 推求水面线.utils import ExcelIO as second
        from 推求水面线.utils.excel_io import ExcelIO as implementation

        assert first is second is implementation
        assert package.ExcelIO is implementation
        assert vars(package)['ExcelIO'] is implementation
        assert importlib.import_module('utils') is package
    """, first_entry)


@pytest.mark.parametrize("backend", ["default", "openpyxl"])
def test_lazy_excel_export_preserves_real_unicode_and_numeric_roundtrip(tmp_path, backend):
    """真正写出并重读临时工作簿，覆盖默认路径和 openpyxl 兼容路径。"""
    _run_isolated("""
        import importlib
        from pathlib import Path
        from 推求水面线.utils import ExcelIO
        from utils import ExcelIO as legacy_excel_io

        module = importlib.import_module('推求水面线.utils.excel_io')
        assert ExcelIO is legacy_excel_io
        assert module.HAS_OPENPYXL
        if sys.argv[2] == 'openpyxl':
            module.HAS_PANDAS = False
        else:
            assert module.HAS_PANDAS
        source = [
            {'建筑物名称': '南支渠 α', '流量(m³/s)': 0.1234567890123,
             '坐标X': 1234.5, '节点序号': 1, '备注': '进口—保留中文'},
            {'建筑物名称': '渡槽二号', '流量(m³/s)': 5.75,
             '坐标X': -6.125, '节点序号': 2, '备注': '出口及加大工况'},
        ]
        target = Path(sys.argv[1])
        handler = ExcelIO()
        handler.write_excel(str(target), source, sheet_name='水面线节点')
        assert target.is_file()
        assert target.read_bytes().startswith(b'PK')
        assert handler.read_excel(str(target), sheet_name='水面线节点') == source
        assert handler.read_excel(str(target)) == source
    """, tmp_path / "中文节点往返.xlsx", backend)


def test_unknown_package_attribute_still_raises_attribute_error():
    """缺少的导出名保持标准模块行为，且不触发 Excel 后端初始化。"""
    _run_isolated("""
        import importlib
        package = importlib.import_module('推求水面线.utils')
        for name in ('UndefinedExport', 'ExcelIO_typo'):
            try:
                getattr(package, name)
            except AttributeError as error:
                assert name in str(error)
            else:
                raise AssertionError('未定义导出必须抛出 AttributeError: ' + name)
        assert 'ExcelIO' not in vars(package)
        assert not any(name.split('.', 1)[0] in {'pandas', 'openpyxl'}
                       for name in sys.modules)
    """)
