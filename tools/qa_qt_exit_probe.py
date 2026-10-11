"""在隔离工作区复现 Qt 测试退出，记录断言结果和真实进程退出码。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--test-file', action='append', default=[])
    parser.add_argument('--destruction-case', choices=['multi-siphon', 'water-profile'])
    parser.add_argument('--json', required=True)
    parser.add_argument('--junit', required=True)
    parser.add_argument('--retain-app', action='store_true')
    parser.add_argument('--drain', action='store_true')
    parser.add_argument('--collect-garbage', action='store_true')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--quiet-lifecycle', action='store_true')
    parser.add_argument('--child', action='store_true')
    return parser.parse_args()


def child(args):
    import faulthandler
    import gc
    import platform

    faulthandler.enable(all_threads=True)
    if sys.platform.startswith('win'):
        def disabled_wmi(*_args, **_kwargs):
            raise OSError('Windows WMI query disabled to avoid startup hang')
        platform._wmi_query = disabled_wmi
        if hasattr(platform, '_wmi'):
            platform._wmi = None
        platform._uname_cache = None
    workspace = Path(args.workspace).resolve()
    os.chdir(workspace)
    sys.path.insert(0, str(workspace))
    from PySide6.QtCore import QCoreApplication, QEvent, QSettings
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.IniFormat)
    for scope in (QSettings.UserScope, QSettings.SystemScope):
        QSettings.setPath(QSettings.IniFormat, scope, str(workspace/'.probe_settings'))

    retained_app = (QApplication.instance() or QApplication([])) if args.retain_app else None
    if args.destruction_case:
        from PySide6.QtTest import QTest
        from shiboken6 import isValid
        retained_app = QApplication.instance() or QApplication([])
        if args.destruction_case == 'multi-siphon':
            from app_渠系计算前端.siphon.multi_siphon_dialog import MultiSiphonDialog
            from 推求水面线.utils.siphon_extractor import SiphonGroup
            widget = MultiSiphonDialog(None, [SiphonGroup(name='销毁时序原始探针')])
        else:
            from app_渠系计算前端.water_profile.panel import WaterProfilePanel
            widget = WaterProfilePanel()
            widget._schedule_adjust_splitter_for_settings()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(widget, QEvent.DeferredDelete)
        print('OWNER_DESTROYED', not isValid(widget), flush=True)
        # 不改回调及异常钩子，观察真正业务方法在销毁后的行为与退出码。
        QTest.qWait(140)
        print('NORMAL_EXIT_BEGIN', 0, flush=True)
        return 0

    def state(stage):
        if args.quiet_lifecycle:
            return
        app = QApplication.instance()
        print('QT_PROBE', json.dumps({'stage': stage, 'app_exists': app is not None,
              'widgets': len(app.allWidgets()) if app else 0,
              'top_levels': len(app.topLevelWidgets()) if app else 0}), flush=True)

    class LifecycleTrace:
        def pytest_runtest_teardown(self, item, nextitem):
            state('teardown:' + item.name)

        def pytest_sessionfinish(self, session, exitstatus):
            state('sessionfinish')

        def pytest_unconfigure(self, config):
            state('unconfigure')

    state('before_collection')
    import pytest
    options = [*args.test_file, '-q', '--tb=short', '-p', 'no:cacheprovider',
               '-p', 'no:hypothesispytest', '--basetemp', str(workspace/'.probe_pytest'),
               '--junitxml', str(Path(args.junit).resolve())]
    if not args.capture:
        options.append('-s')
    code = pytest.main(options, plugins=[] if args.quiet_lifecycle else [LifecycleTrace()])
    print('PYTEST_RETURNED', int(code), flush=True)
    state('after_pytest')
    if args.drain:
        app = QApplication.instance()
        if app:
            # 只在明确选择的探针分支处理已排队事件，不强制删除控件。
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
        state('after_drain')
    if args.collect_garbage:
        print('GC_COLLECT_START', flush=True)
        print('GC_COLLECTED', gc.collect(), flush=True)
        state('after_gc')
    print('NORMAL_EXIT_BEGIN', int(code), bool(retained_app), flush=True)
    return int(code)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    args = parse_args()
    if args.child:
        return child(args)
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', CODEX_FORCE_QTEXTBROWSER='1',
                       QTWEBENGINE_DISABLE_SANDBOX='1', PYTHONIOENCODING='utf-8')
    start = time.monotonic()
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--child'],
                            env=environment, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=120)
    record = {'arguments': vars(args), 'exit_code': result.returncode,
              'exit_code_hex': hex(result.returncode & 0xffffffff),
              'elapsed_seconds': round(time.monotonic()-start, 3),
              'stdout': result.stdout, 'stderr': result.stderr,
              'normal_exit_requested': 'NORMAL_EXIT_BEGIN' in result.stdout,
              'pytest_returned': 'PYTEST_RETURNED' in result.stdout}
    # 保存被测文件指纹，让后续复核能够区分代码变化与进程退出差异。
    workspace = Path(args.workspace).resolve()
    sources = [*args.test_file,
               'app_渠系计算前端/bootstrap.py',
               'app_渠系计算前端/siphon/multi_siphon_dialog.py',
               'app_渠系计算前端/siphon/panel.py',
               'app_渠系计算前端/water_profile/panel.py']
    record['source_sha256'] = {
        relative: hashlib.sha256((workspace/relative).read_bytes()).hexdigest()
        for relative in sources if (workspace/relative).is_file()}
    record['probe_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    record['python_executable'] = sys.executable
    destination = Path(args.json).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(result.stdout)
    print(result.stderr)
    print('ACTUAL_EXIT', record['exit_code_hex'], flush=True)
    return 0 if result.returncode == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
