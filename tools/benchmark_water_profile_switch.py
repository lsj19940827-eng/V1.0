"""在独立 Qt 进程中测量主窗口首次点击水面线导航，不写入用户工程。"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import importlib
import json
import os
from pathlib import Path
import pstats
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MARKER = "WATER_PROFILE_SWITCH_BENCHMARK="


def source_digests():
    """记录实际工作区源码，避免把并行改动期间的不同版本混入一组样本。"""
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ("推求水面线/utils/__init__.py", "app_渠系计算前端/water_profile/panel.py",
                     "app_渠系计算前端/batch/panel.py", "app_渠系计算前端/app.py")
    }


def child(args):
    sources_before = source_digests()
    sys.path.insert(0, str(ROOT))
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from app_渠系计算前端.bootstrap import initialize_runtime_environment, ensure_application
    from app_渠系计算前端.qfluentwidgets_compat import ensure_qfluentwidgets_compat

    initialize_runtime_environment()
    ensure_qfluentwidgets_compat()
    app = ensure_application([])
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QTimer, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from app_渠系计算前端 import app as app_module
    from app_渠系计算前端.startup_context import StartupContext

    timings = {}

    def measured_factory(*, siphon_manager, pressure_pipe_manager):
        started = time.perf_counter()
        module = importlib.import_module("app_渠系计算前端.water_profile.panel")
        timings["import_ms"] = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        panel = module.WaterProfilePanel(
            siphon_manager=siphon_manager, pressure_pipe_manager=pressure_pipe_manager,
        )
        timings["construct_ms"] = (time.perf_counter() - started) * 1000
        return panel

    app_module._create_water_profile_panel = measured_factory
    window = app_module.MainWindow(StartupContext(
        webengine_mode="standard", webengine_probe_result=None,
        update_checks_enabled=False, is_frozen_runtime=False,
    ))
    window.project_manager._auto_save_timer.stop()
    window.show()
    QTest.qWait(400)
    assert window._panel_registry.get_existing("water_profile") is None
    gaps = []
    last_tick = time.perf_counter()

    def tick():
        nonlocal last_tick
        now = time.perf_counter()
        gaps.append((now - last_tick) * 1000)
        last_tick = now

    timer = QTimer(window)
    timer.setInterval(10)
    timer.timeout.connect(tick)
    timer.start()
    QTest.qWait(40)
    gaps.clear()
    last_tick = time.perf_counter()
    profile = cProfile.Profile() if args.profile else None
    if profile:
        profile.enable()
    started = time.perf_counter()
    QTest.mouseClick(window._nav_buttons[6], Qt.LeftButton)
    timings["click_handler_ms"] = (time.perf_counter() - started) * 1000
    app.processEvents()
    timings["first_display_ms"] = (time.perf_counter() - started) * 1000
    QTest.qWait(120)
    if profile:
        profile.disable()
        stats = pstats.Stats(profile)
        timings["profile_top"] = [
            {"file": key[0], "line": key[1], "function": key[2],
             "calls": value[1], "total_ms": value[2] * 1000, "cumulative_ms": value[3] * 1000}
            for key, value in sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)[:55]
        ]
    timings["event_loop_max_gap_ms"] = max(gaps, default=0)
    timer.stop()
    panel = window._panel_registry.get_existing("water_profile")
    assert window.stack.currentWidget() is panel
    assert panel._section_input_table is panel._batch_backend.input_table
    assert panel._section_result_table is panel._batch_backend.result_table
    timings["input_rows"] = panel._section_input_table.rowCount()
    timings["platform"] = app.platformName()
    timings["python_version"] = sys.version
    import PySide6
    timings["pyside_version"] = PySide6.__version__
    timings["window_visible"] = window.isVisible()
    repeats = []
    for _ in range(3):
        QTest.mouseClick(window._nav_buttons[0], Qt.LeftButton)
        app.processEvents()
        started = time.perf_counter()
        QTest.mouseClick(window._nav_buttons[6], Qt.LeftButton)
        app.processEvents()
        repeats.append((time.perf_counter() - started) * 1000)
        assert window.stack.currentWidget() is panel
    timings["repeat_display_ms"] = repeats
    if args.hover:
        # 单独测量被延后的提示创建，并确认真实公式图片仍可显示。
        tabs = panel._workspace_tabs
        QTest.mouseClick(tabs.tabBar(), Qt.LeftButton, pos=tabs.tabBar().tabRect(2).center())
        app.processEvents()
        module = importlib.import_module("app_渠系计算前端.water_profile.panel")
        header = panel._node_header
        column = module.NODE_ALL_HEADERS.index("转角")
        panel.node_table.horizontalScrollBar().setValue(header.sectionPosition(column))
        app.processEvents()
        position = QPoint(header.sectionViewportPosition(column) + header.sectionSize(column)//2,
                          header.height()//2)
        assert header.logicalIndexAt(position) == column
        event = QMouseEvent(QEvent.MouseMove, QPointF(position),
                            QPointF(header.mapToGlobal(position)), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        started = time.perf_counter()
        QCoreApplication.sendEvent(header.viewport(), event)
        timings["first_hover_handler_ms"] = (time.perf_counter() - started) * 1000
        QTest.qWait(450)
        tooltip = panel._formula_tooltip
        assert tooltip._current_col == "转角" and tooltip.isVisible()
        assert not tooltip._formula_label.pixmap().isNull()
        timings["formula_pixmap_displayed"] = True
    # 正常销毁并推进延迟回调，不能用强制退出掩盖 Qt 生命周期问题。
    window.hide()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QTest.qWait(150)
    assert source_digests() == sources_before, "采样期间源码发生变化，请重新测量"
    timings["source_sha256"] = sources_before
    print(MARKER + json.dumps(timings, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--hover", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    runs = []
    for index in range(args.runs):
        command = [sys.executable, str(Path(__file__).resolve()), "--child"]
        if args.offscreen:
            command.append("--offscreen")
        if args.profile:
            command.append("--profile")
        if args.hover:
            command.append("--hover")
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=90)
        if result.returncode:
            raise RuntimeError(f"独立进程退出码 {result.returncode}: {result.stderr[-4000:]}\n{result.stdout[-2000:]}")
        record = next(line[len(MARKER):] for line in result.stdout.splitlines() if line.startswith(MARKER))
        runs.append(json.loads(record))
        print(f"第 {index + 1} 轮首次显示 {runs[-1]['first_display_ms']:.1f} ms", flush=True)
    sources = source_digests()
    assert all(run["source_sha256"] == sources for run in runs), "各轮源码不同，请重新测量"
    report = {"runs": runs, "source_sha256": sources, "median_ms": {
        key: statistics.median(run[key] for run in runs)
        for key in ("import_ms", "construct_ms", "click_handler_ms", "first_display_ms", "event_loop_max_gap_ms")
    }, "repeat_median_ms": statistics.median(value for run in runs for value in run["repeat_display_ms"])}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "runs"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
