"""用独立 Qt 进程比较表1交互与稀疏工程打开，不写入用户工程。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    'app_渠系计算前端/batch/panel.py',
    'app_渠系计算前端/water_profile/panel.py',
    'app_渠系计算前端/project_manager.py',
]
MARKER = 'BATCH_EDIT_BENCHMARK='


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def child(args):
    sys.path.insert(0, str(ROOT))
    os.environ.update(QT_QPA_PLATFORM='offscreen', CODEX_FORCE_QTEXTBROWSER='1')
    from app_渠系计算前端.bootstrap import initialize_runtime_environment, ensure_application
    from app_渠系计算前端.qfluentwidgets_compat import ensure_qfluentwidgets_compat
    initialize_runtime_environment()
    ensure_qfluentwidgets_compat()
    app = ensure_application([])
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QTableWidgetItem
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont('Microsoft YaHei', 10))

    with tempfile.TemporaryDirectory(prefix='batch-edit-bench-', dir=ROOT/'tools/_tmp_test_outputs') as temp:
        if args.scenario == 'open':
            from app_渠系计算前端 import app as app_module
            from app_渠系计算前端.startup_context import StartupContext
            app_module.ProjectManager.start_auto_save = lambda self: None

            def services(self):
                self.siphon_manager = None
                self.pressure_pipe_manager = None

            def siphon_factory(**kwargs):
                from app_渠系计算前端.siphon import panel as siphon_module
                siphon_module._pkg_root = temp
                return siphon_module.SiphonPanel(disable_autosave_load=True, **kwargs)

            app_module.MainWindow._init_runtime_services = services
            app_module._create_siphon_panel = siphon_factory
            target = app_module.MainWindow(StartupContext(
                webengine_mode='standard', webengine_probe_result=None,
                update_checks_enabled=False, is_frozen_runtime=False,
            ))
            app.processEvents()
            original = target.open_channel_panel.to_project_dict()
            project = Path(temp)/'稀疏工程.qxproj'
            project.write_text(json.dumps({'open_channel_panel': original}, ensure_ascii=False), encoding='utf-8')
            started = time.perf_counter()
            target.project_manager._load_from_file(str(project))
            app.processEvents()
            elapsed = (time.perf_counter()-started)*1000
            assert target.open_channel_panel.to_project_dict() == original
            result = {'open_ms': elapsed, 'created_panels': len(target._panel_registry.iter_instances()),
                      'active_payload_equal': True}
            for panel in target._panel_registry.iter_instances():
                if hasattr(panel, '_autosave_timer'):
                    panel._autosave_timer.stop()
        else:
            from app_渠系计算前端.water_profile.panel import WaterProfilePanel
            from app_渠系计算前端.batch import panel as batch_module
            target = WaterProfilePanel()
            target.resize(1420, 920)
            batch_module.InfoBar.success = lambda *a, **k: None
            backend = target._batch_backend
            table = backend.input_table
            table.blockSignals(True)
            table.setRowCount(args.rows)
            rows = []
            for r in range(args.rows):
                values = ['']*table.columnCount()
                for col, value in {
                    batch_module.COL_SEQ: str(r+1), batch_module.COL_SEGMENT: '1',
                    batch_module.COL_BUILDING_NAME: f'节点{r+1}', batch_module.COL_SECTION_TYPE: '明渠-梯形',
                    batch_module.COL_Q: '1.23456789012345', batch_module.COL_N: '0.014',
                    batch_module.COL_SLOPE: '3000', batch_module.COL_M: '1.5',
                    batch_module.COL_V_MIN: '0.1', batch_module.COL_V_MAX: '100',
                }.items():
                    values[col] = value
                rows.append(values)
                for col, value in enumerate(values):
                    table.setItem(r, col, QTableWidgetItem(value))
            table.blockSignals(False)
            backend._table_undo_stack.clear()
            backend._table_redo_stack.clear()
            target.show()
            app.processEvents()
            counts = {'snapshots': 0, 'data_changed': 0}
            original_snapshot = backend._snapshot_table

            def counted_snapshot():
                counts['snapshots'] += 1
                return original_snapshot()

            def changed():
                counts['data_changed'] += 1

            backend._snapshot_table = counted_snapshot
            backend.data_changed.connect(changed)
            started = time.perf_counter()
            for r in range(100):
                table.setCurrentCell(r % args.rows, batch_module.COL_BUILDING_NAME)
            app.processEvents()
            selection_ms = (time.perf_counter()-started)*1000
            selection_snapshots = counts['snapshots']
            table.setCurrentCell(0, 0)
            counts.update(snapshots=0, data_changed=0)
            for r, values in enumerate(rows):
                values[batch_module.COL_BUILDING_NAME] = f'粘贴节点{r+1}'
            app.clipboard().setText('\n'.join('\t'.join(row) for row in rows))
            started = time.perf_counter()
            backend._paste_from_clipboard()
            app.processEvents()
            paste_ms = (time.perf_counter()-started)*1000
            snapshot = original_snapshot()
            result = {
                'selection_ms': selection_ms, 'paste_ms': paste_ms,
                'selection_snapshots': selection_snapshots,
                'paste_snapshots': counts['snapshots'], 'paste_notifications': counts['data_changed'],
                'undo_steps': len(backend._table_undo_stack), 'rows': table.rowCount(),
                'columns': table.columnCount(),
                'state_digest': digest({'rows': snapshot['rows'], 'row_meta': snapshot['row_meta'],
                                        'flow': backend.flow_segments_edit.text()}),
            }
            if args.screenshot:
                assert target.grab().save(args.screenshot)
        target.hide()
        target.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print(MARKER+json.dumps(result, ensure_ascii=False), flush=True)
    # 所有测试控件与临时文件已释放，避免 Qt 插件解释器退出顺序影响测量进程。
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--scenario', choices=['table', 'open'], default='table')
    parser.add_argument('--phase', choices=['before', 'after'], default='after')
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--rows', type=int, default=400)
    parser.add_argument('--output', default='docs/qa/batch_editing_performance_20261009.json')
    parser.add_argument('--screenshot')
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    output = ROOT/args.output
    report = json.loads(output.read_text(encoding='utf-8')) if output.exists() else {}
    measurement = {'source_sha256': {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in SOURCES},
                   'recorded_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'scenarios': {}}
    for scenario in ('table', 'open'):
        samples = []
        for index in range(args.samples):
            command = [sys.executable, __file__, '--child', '--scenario', scenario, '--rows', str(args.rows)]
            if args.screenshot and scenario == 'table' and index == args.samples-1:
                command += ['--screenshot', str(Path(args.screenshot).resolve())]
            proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=180, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
            lines = [line for line in proc.stdout.splitlines() if line.startswith(MARKER)]
            if proc.returncode or not lines:
                raise RuntimeError(f'{scenario} #{index+1}: {proc.returncode}\n{proc.stdout[-3500:]}\n{proc.stderr[-3500:]}')
            value = json.loads(lines[-1][len(MARKER):])
            samples.append(value)
            print(f'{args.phase} {scenario} {index+1}/{args.samples}: {value}', flush=True)
        medians = {key: statistics.median(value[key] for value in samples)
                   for key in samples[0] if key.endswith('_ms')}
        measurement['scenarios'][scenario] = {'samples': samples, 'medians': medians}
    if args.phase in report:
        report.setdefault('previous_measurements', []).append({'phase': args.phase, **report[args.phase]})
    report[args.phase] = measurement
    if 'before' in report and 'after' in report:
        states = {sample['state_digest'] for phase in ('before', 'after')
                  for sample in report[phase]['scenarios']['table']['samples']}
        report['table_state_equal'] = len(states) == 1
        assert report['table_state_equal'], '优化前后的表格数据不一致'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
