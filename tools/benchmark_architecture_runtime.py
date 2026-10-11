"""测量真实水面线按钮与表格路径，可只读对照本轮改动前的源码归档。"""

from __future__ import annotations

import argparse
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MARKER = "ARCHITECTURE_BENCHMARK="


class ArchiveSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """仅替换归档中已有的生产源码，不切分支、不覆盖工作区。"""

    def __init__(self, archive):
        with zipfile.ZipFile(archive) as source:
            self.sources = {name: source.read(name) for name in source.namelist() if name.endswith('.py')}

    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or not spec.origin:
            return None
        try:
            relative = Path(spec.origin).relative_to(ROOT).as_posix()
        except ValueError:
            return None
        if relative not in self.sources:
            return None
        return importlib.util.spec_from_file_location(
            fullname, spec.origin, loader=self,
            submodule_search_locations=spec.submodule_search_locations)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        key = Path(module.__file__).relative_to(ROOT).as_posix()
        exec(compile(self.sources[key], module.__file__, 'exec'), module.__dict__)


def child(args):
    os.environ.update(QT_QPA_PLATFORM='offscreen', CODEX_FORCE_QTEXTBROWSER='1')
    sys.path.insert(0, str(ROOT))
    if args.source_archive:
        sys.meta_path.insert(0, ArchiveSources(args.source_archive))
    from app_渠系计算前端.bootstrap import initialize_runtime_environment, ensure_application
    from app_渠系计算前端.qfluentwidgets_compat import ensure_qfluentwidgets_compat
    initialize_runtime_environment()
    ensure_qfluentwidgets_compat()
    app = ensure_application([])
    from PySide6.QtCore import QTimer, Qt, QCoreApplication, QEvent
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QTableWidgetSelectionRange
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont('Microsoft YaHei', 10))
    from app_渠系计算前端.water_profile import panel as module
    from 推求水面线.models.data_models import ChannelNode
    from 推求水面线.models.enums import StructureType, InOutType
    for name in ('warning', 'error', 'info', 'success'):
        setattr(module.InfoBar, name, lambda *a, **k: None)
    started = time.perf_counter()
    panel = module.WaterProfilePanel()
    construction_ms = (time.perf_counter() - started) * 1000
    panel.resize(1420, 920)
    panel.start_wl_edit.setText('1000')
    panel.design_flow_edit.setText('2.5')
    panel.max_flow_edit.setText('3.0')
    panel.roughness_edit.setText('0.014')
    nodes = []
    for index in range(args.rows):
        node = ChannelNode()
        node.structure_type = StructureType.from_string('明渠-梯形')
        node.in_out = InOutType.NORMAL
        node.flow_section = '1'
        node.x, node.y = index * 100.123456789, 0
        node.flow = node.design_flow = 2.5
        node.roughness, node.slope_i = 0.014, 0.0005
        node.water_depth, node.structure_height = 1.234567890123, 2.4
        node.section_params.update({'b': 2.0, 'B': 2.0, 'm': 1.5})
        nodes.append(node)
    panel._update_table_from_nodes_full(nodes)
    panel._section_sync_ready = True
    panel._transition_topology_prepared = True
    panel._switch_workspace_tab(panel._tab_water_profile)
    panel.show()
    app.processEvents()
    panel._show_calculation_completion_notice = lambda *a, **k: None
    panel._btn_calc.setEnabled(True)
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start()
    started = time.perf_counter()
    panel._btn_calc.click()
    returned = time.perf_counter()
    running = getattr(panel, 'is_calculation_running', lambda: False)
    ticks_before_complete = 0
    while running():
        app.processEvents()
        if running():
            ticks_before_complete = len(ticks)
        if time.perf_counter() - started > 120:
            raise RuntimeError('水面线按钮计算超时')
        time.sleep(0.001)
    finished = time.perf_counter()
    timer.stop()
    assert len(panel.calculated_nodes) == args.rows
    computation_values = [
        [getattr(node, key) for key in ('x', 'y', 'station_MC', 'water_level',
          'bottom_elevation', 'head_loss_total', 'head_loss_cumulative')]
        for node in panel.calculated_nodes
    ]
    # 测量此前已优化的连续选格和多格删除，观察本轮是否造成交互回退。
    table = panel.node_table
    started_selection = time.perf_counter()
    for index in range(1, min(args.rows, 101)):
        table.setCurrentCell(index, 36)
    selection_ms = (time.perf_counter() - started_selection) * 1000
    panel._loss_undo_stack.clear()
    table.clearSelection()
    table.setRangeSelected(QTableWidgetSelectionRange(10, 36, min(49, args.rows - 1), 37), True)
    started_delete = time.perf_counter()
    table._delete_selected_cells()
    delete_ms = (time.perf_counter() - started_delete) * 1000
    started_save = time.perf_counter()
    payload = panel.to_project_dict()
    collect_ms = (time.perf_counter() - started_save) * 1000
    result = {
        'rows': args.rows, 'columns': table.columnCount(), 'construction_ms': construction_ms,
        'button_return_ms': (returned - started) * 1000,
        'calculation_and_render_ms': (finished - started) * 1000,
        'ui_timer_ticks_before_completion': ticks_before_complete,
        'selection_100_ms': selection_ms, 'delete_80_cells_ms': delete_ms,
        'delete_undo_steps': len(panel._loss_undo_stack), 'collect_project_ms': collect_ms,
        'serialized_bytes': len(json.dumps(payload, ensure_ascii=False).encode('utf-8')),
        'numerical_values': computation_values,
    }
    assert result['delete_undo_steps'] == 1
    if args.screenshot:
        panel._switch_workspace_tab(panel._tab_water_profile)
        app.processEvents()
        if not panel.grab().save(args.screenshot):
            raise RuntimeError('保存截图失败')
    panel.hide()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print(MARKER + json.dumps(result, ensure_ascii=False), flush=True)
    # 独立进程不触发真实用户工程的 closeEvent/自动存档。
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-archive')
    parser.add_argument('--source-archive')
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--rows', type=int, default=400)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--screenshot')
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    phases = [('after', '')]
    if args.baseline_archive:
        phases.insert(0, ('before', args.baseline_archive))
    report = {'environment': '真实Qt控件，离屏QTextBrowser；包含报告生成及表格写回，非安装包验收',
              'rows': args.rows, 'runs': args.runs, 'samples': {}, 'medians': {}}
    numerical = {}
    for phase, archive in phases:
        samples = []
        for run in range(args.runs):
            command = [sys.executable, str(Path(__file__).resolve()), '--child', '--rows', str(args.rows)]
            if archive:
                command += ['--source-archive', archive]
            if phase == 'after' and run == args.runs - 1 and args.screenshot:
                command += ['--screenshot', args.screenshot]
            process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=150)
            lines = [line[len(MARKER):] for line in process.stdout.splitlines() if line.startswith(MARKER)]
            if process.returncode or not lines:
                raise RuntimeError(process.stdout[-3000:] + process.stderr[-3000:])
            result = json.loads(lines[-1])
            values = result.pop('numerical_values')
            if phase in numerical:
                assert numerical[phase] == values
            numerical[phase] = values
            samples.append(result)
            print(f'{phase}: {run + 1}/{args.runs}', flush=True)
        report['samples'][phase] = samples
        report['medians'][phase] = {key: statistics.median(sample[key] for sample in samples) for key in samples[0]}
    if 'before' in numerical:
        report['numerical_values_equal'] = numerical['before'] == numerical['after']
        assert report['numerical_values_equal'], '同输入水面线结果发生变化'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['medians'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
