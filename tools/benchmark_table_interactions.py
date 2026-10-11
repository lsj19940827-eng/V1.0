"""对照历史源码测量表3交互与首次保存的数据收集，不改写工程或切换 Git 分支。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'app_渠系计算前端.styles': 'app_渠系计算前端/styles.py',
    'app_渠系计算前端.frozen_table': 'app_渠系计算前端/frozen_table.py',
    'app_渠系计算前端.water_profile.panel': 'app_渠系计算前端/water_profile/panel.py',
    'app_渠系计算前端.project_manager': 'app_渠系计算前端/project_manager.py',
    'app_渠系计算前端.app': 'app_渠系计算前端/app.py',
    'app_渠系计算前端.batch.panel': 'app_渠系计算前端/batch/panel.py',
    'app_渠系计算前端.siphon.panel': 'app_渠系计算前端/siphon/panel.py',
}
MARKER = 'TABLE_BENCHMARK='


class HistoricalSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """仅在子进程中导入指定版本的模块，依赖与运行环境保持一致。"""

    def __init__(self, ref):
        self.sources = {
            module: subprocess.check_output(['git', 'show', f'{ref}:{path}'], cwd=ROOT)
            for module, path in SOURCES.items()
        }

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.sources:
            return importlib.util.spec_from_file_location(fullname, ROOT / SOURCES[fullname], loader=self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(compile(self.sources[module.__name__], module.__file__, 'exec'), module.__dict__)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def child(args):
    """使用真实 Qt 表格；结果网页以 QTextBrowser 替代，测量不涉及网页加载速度。"""
    sys.path.insert(0, str(ROOT))
    os.environ.update(QT_QPA_PLATFORM='offscreen', CODEX_FORCE_QTEXTBROWSER='1')
    if args.source_ref:
        sys.meta_path.insert(0, HistoricalSources(args.source_ref))
    from app_渠系计算前端.bootstrap import initialize_runtime_environment, ensure_application
    from app_渠系计算前端.qfluentwidgets_compat import ensure_qfluentwidgets_compat
    initialize_runtime_environment()
    ensure_qfluentwidgets_compat()
    app = ensure_application([])
    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QTableWidgetSelectionRange
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont('Microsoft YaHei', 10))

    if args.scenario == 'save':
        from app_渠系计算前端.app import MainWindow
        from app_渠系计算前端.startup_context import StartupContext
        window = MainWindow(StartupContext(
            webengine_mode='standard', webengine_probe_result=None,
            update_checks_enabled=False, is_frozen_runtime=False,
        ))
        window.project_manager.stop_auto_save()
        before = len(window._panel_registry.iter_instances())
        active_before = window.open_channel_panel.to_project_dict()
        started = time.perf_counter()
        payload = window.project_manager._collect_project_data()
        elapsed = (time.perf_counter() - started) * 1000
        assert payload['open_channel_panel'] == active_before
        result = {
            'collect_ms': elapsed, 'panels_before': before,
            'panels_after': len(window._panel_registry.iter_instances()),
            'active_payload_preserved': True,
        }
    else:
        from app_渠系计算前端.water_profile.panel import WaterProfilePanel
        from 推求水面线.models.data_models import ChannelNode
        from 推求水面线.models.enums import StructureType
        panel = WaterProfilePanel()
        panel.resize(1420, 920)
        panel.start_wl_edit.setText('1000')
        nodes = []
        cumulative = 0.0
        for row in range(args.rows):
            node = ChannelNode()
            node.name = f'测量节点{row}'
            node.flow_section = '1'
            node.structure_type = StructureType.from_string('明渠-梯形')
            node.flow = 1.25
            node.water_depth = 1.2
            node.section_params = {'B': 2.0, 'm': 1.0, 'h': 1.2}
            node.station_MC = row * 20.0
            node.head_loss_reserve = 0.123456789 if row else 0.0
            node.head_loss_gate = 0.234567891 if row else 0.0
            node.head_loss_total = node.head_loss_reserve + node.head_loss_gate
            cumulative += node.head_loss_total
            node.head_loss_cumulative = cumulative
            node.water_level = 1000.0 - cumulative
            node.bottom_elevation = node.water_level - node.water_depth
            node.top_elevation = node.bottom_elevation + 2.0
            nodes.append(node)
        panel.calculated_nodes = nodes
        panel.nodes = nodes
        panel._node_structure_heights = {r: 2.0 for r in range(args.rows)}
        panel._update_table_from_nodes_full(nodes)
        panel._section_sync_ready = True
        panel._switch_workspace_tab(panel._tab_water_profile)
        panel.show()
        QTest.qWait(160)
        table = panel.node_table
        widths_before = [table.columnWidth(c) for c in range(table.columnCount())]

        measurements = []
        original_measure = table.resizeColumnsToContents

        def measure():
            measurements.append(1)
            return original_measure()

        table.resizeColumnsToContents = measure
        started = time.perf_counter()
        for step in range(12):
            panel.resize(1300 + step * 13, 900 + step % 3)
            app.processEvents()
        burst_done = time.perf_counter()
        timer = getattr(table, '_column_resize_timer', None)
        if timer is not None and timer.isActive():
            loop = QEventLoop()
            timer.timeout.connect(loop.quit)
            guard = QTimer()
            guard.setSingleShot(True)
            guard.timeout.connect(loop.quit)
            guard.start(5000)
            loop.exec()
            guard.stop()
            timer.timeout.disconnect(loop.quit)
            if timer.isActive():
                raise RuntimeError('列宽刷新未完成')
        settled = time.perf_counter()
        resize_result = {
            'resize_burst_ms': (burst_done - started) * 1000,
            'resize_settled_ms': (settled - started) * 1000,
            'resize_content_scans': len(measurements),
            'widths_before': widths_before,
            'widths_after': [table.columnWidth(c) for c in range(table.columnCount())],
        }

        snapshots = []
        original_snapshot = panel._snapshot_editable_cols

        def snapshot():
            snapshots.append(1)
            return original_snapshot()

        panel._snapshot_editable_cols = snapshot
        started = time.perf_counter()
        for row in range(1, 101):
            table.setCurrentCell(row, 36)
        selection_ms = (time.perf_counter() - started) * 1000
        selection_snapshots = len(snapshots)

        panel._loss_undo_stack.clear()
        table.clearSelection()
        table.setRangeSelected(QTableWidgetSelectionRange(10, 36, 49, 37), True)
        refreshes = []
        dirty = []
        original_refresh = panel._refresh_pressure_pipe_controls

        def refresh():
            refreshes.append(1)
            return original_refresh()

        panel._refresh_pressure_pipe_controls = refresh
        panel.data_changed.connect(lambda: dirty.append(1))
        started = time.perf_counter()
        table._delete_selected_cells()
        delete_ms = (time.perf_counter() - started) * 1000
        state = [
            {
                'texts': [table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())],
                'metadata': table.item(r, 0).data(Qt.UserRole),
                'node': node.to_project_dict(),
            }
            for r, node in enumerate(panel.calculated_nodes)
        ]
        assert len(panel._loss_undo_stack) == 1
        result = {
            **resize_result, 'selection_ms': selection_ms,
            'selection_snapshots': selection_snapshots,
            'delete_ms': delete_ms, 'delete_refreshes': len(refreshes),
            'delete_dirty_signals': len(dirty), 'delete_undo_steps': len(panel._loss_undo_stack),
            'state_sha256': digest(state), 'rows': args.rows, 'columns': table.columnCount(),
        }
        if args.screenshot:
            table.scrollToItem(table.item(10, 36))
            app.processEvents()
            path = Path(args.screenshot)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not panel.grab().save(str(path)):
                raise RuntimeError('界面截图保存失败')
    # 销毁测试窗口而不发送 closeEvent，避免触发真实工程的关闭保存。
    target = window if args.scenario == 'save' else panel
    target.hide()
    target.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print(MARKER + json.dumps(result, ensure_ascii=False), flush=True)
    # Qt 的异步关闭不属于本次测量，保留独立进程隔离。
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='HEAD')
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--rows', type=int, default=400)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--screenshot')
    parser.add_argument('--refresh-current', action='store_true', help='复用已有历史样本，仅复测当前源码')
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--source-ref', default='')
    parser.add_argument('--scenario', choices=['table', 'save'], default='table')
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    if args.rows < 101 or args.runs < 1:
        parser.error('测量至少需要 101 行、1 次重复')
    baseline = subprocess.check_output(['git', 'rev-parse', args.baseline_ref], cwd=ROOT, text=True).strip()
    report = {
        'baseline_ref': baseline, 'runs': args.runs,
        'runtime': 'PySide6 offscreen; actual QTableWidget; QTextBrowser result view',
        'source_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCES.values()},
        'before': {'table': [], 'save': []}, 'after': {'table': [], 'save': []},
    }
    phases = [('before', baseline), ('after', '')]
    if args.refresh_current:
        if args.output is None or not args.output.is_file():
            parser.error('仅复测当前源码时，必须指定已有的 --output 报告')
        previous = json.loads(args.output.read_text(encoding='utf-8'))
        if previous['baseline_ref'] != baseline or previous['runs'] != args.runs:
            parser.error('历史版本或重复次数与已有报告不一致')
        if any(row['rows'] != args.rows for row in previous['before']['table']):
            parser.error('表格行数与已有历史样本不一致')
        report['before'] = previous['before']
        report['prior_after'] = previous['after']
        report['prior_source_sha256'] = previous['source_sha256']
        phases = [('after', '')]
    for phase, ref in phases:
        for scenario in ('table', 'save'):
            for run in range(args.runs):
                command = [sys.executable, str(Path(__file__).resolve()), '--child', '--source-ref', ref,
                           '--scenario', scenario, '--rows', str(args.rows)]
                if phase == 'after' and scenario == 'table' and run == args.runs - 1 and args.screenshot:
                    command += ['--screenshot', args.screenshot]
                process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                                         errors='replace', timeout=120, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
                rows = [line[len(MARKER):] for line in process.stdout.splitlines() if line.startswith(MARKER)]
                if process.returncode or not rows:
                    raise RuntimeError(f'子进程退出码={process.returncode}，结果记录数={len(rows)}\n'
                                       + process.stdout[-3000:] + process.stderr[-3000:])
                report[phase][scenario].append(json.loads(rows[-1]))
                print(f'{phase} {scenario} {run + 1}/{args.runs} completed', flush=True)
    if any(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != value
           for path, value in report['source_sha256'].items()):
        raise RuntimeError('测量过程中源码发生变化，请固定当前源码后重新测量')
    report['state_equal'] = len({item['state_sha256'] for phase in ('before', 'after') for item in report[phase]['table']}) == 1
    report['medians'] = {
        phase: {key: statistics.median(item[key] for item in report[phase][scenario])
                for scenario, keys in (
                    ('table', ('resize_burst_ms', 'resize_settled_ms', 'selection_ms', 'delete_ms')),
                    ('save', ('collect_ms',)),
                ) for key in keys}
        for phase in ('before', 'after')
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'medians': report['medians'], 'state_equal': report['state_equal']}, ensure_ascii=False, indent=2))
    if not report['state_equal']:
        raise SystemExit('数值/文本/元数据对照不同，不能作为优化验收通过')


if __name__ == '__main__':
    main()
