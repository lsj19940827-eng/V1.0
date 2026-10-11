"""用独立 Qt 进程复测从明渠页首次进入有压管道页，可只读对照历史源码。"""

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
SOURCE_MODULES = {
    "有压管道设计": "calc_渠系计算算法内核/有压管道设计.py",
    "calc_渠系计算算法内核.unpressurized_comparison": "calc_渠系计算算法内核/unpressurized_comparison.py",
    "app_渠系计算前端.pressure_pipe.panel": "app_渠系计算前端/pressure_pipe/panel.py",
    "app_渠系计算前端.pressure_pipe.slope_controls": "app_渠系计算前端/pressure_pipe/slope_controls.py",
    "app_渠系计算前端.formula_renderer": "app_渠系计算前端/formula_renderer.py",
}
MARKER = "BENCHMARK_RESULT="


class _HistoricalSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """只在测量子进程内替换指定模块源码，不切分支或改写工作区。"""

    def __init__(self, ref):
        self.sources = {
            module: subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT)
            for module, path in SOURCE_MODULES.items()
        }

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.sources:
            return importlib.util.spec_from_file_location(
                fullname, ROOT / SOURCE_MODULES[fullname], loader=self,
            )
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(compile(self.sources[module.__name__], module.__file__, "exec"), module.__dict__)


def _measure_child(args):
    """模拟正常明渠首页已显示后的首次点击，保留真实 WebEngine 和公式渲染。"""
    sys.path.insert(0, str(ROOT))
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
    os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    os.environ.pop("CODEX_FORCE_QTEXTBROWSER", None)
    if args.source_ref:
        sys.meta_path.insert(0, _HistoricalSources(args.source_ref))

    from app_渠系计算前端.bootstrap import initialize_runtime_environment, ensure_application
    from app_渠系计算前端.qfluentwidgets_compat import ensure_qfluentwidgets_compat
    initialize_runtime_environment()
    ensure_qfluentwidgets_compat()
    app = ensure_application([])
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QStackedWidget
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
    if font_path.is_file():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont("Microsoft YaHei", 10))
    from app_渠系计算前端.open_channel.panel import OpenChannelPanel

    def display_and_wait(panel, display):
        """等待页面真实加载完成，超时或失败不生成成功的测量值。"""
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        finished = []
        view = getattr(panel, "result_view", None) or panel.result_text

        def on_loaded(ok):
            finished.append(bool(ok))
            loop.quit()

        view.loadFinished.connect(on_loaded)
        try:
            timeout.start(15000)
            display()
            if not finished:
                loop.exec()
            if not finished or not finished[-1]:
                raise RuntimeError("结果页加载失败或超时，不能作为性能通过记录")
            app.processEvents()
        finally:
            timeout.stop()
            view.loadFinished.disconnect(on_loaded)

    landing = OpenChannelPanel()
    stack = QStackedWidget()
    stack.resize(1380, 850)
    stack.addWidget(landing)
    display_and_wait(landing, stack.show)
    before_modules = set(sys.modules)

    start = time.perf_counter()
    from app_渠系计算前端.pressure_pipe.panel import PressurePipePanel
    imported = time.perf_counter()
    panel = PressurePipePanel()
    constructed = time.perf_counter()
    stack.addWidget(panel)
    display_and_wait(panel, lambda: stack.setCurrentWidget(panel))
    ready = time.perf_counter()
    repeated = []
    for _ in range(5):
        stack.setCurrentWidget(landing)
        app.processEvents()
        begin = time.perf_counter()
        stack.setCurrentWidget(panel)
        app.processEvents()
        repeated.append((time.perf_counter() - begin) * 1000)
    data = {
        "import_ms": (imported - start) * 1000,
        "construction_ms": (constructed - imported) * 1000,
        "display_ready_ms": (ready - constructed) * 1000,
        "first_entry_ms": (ready - start) * 1000,
        "repeat_switch_ms": statistics.median(repeated),
        "batch_libraries_newly_loaded": [
            name for name in ("pandas", "scipy.optimize")
            if name in sys.modules and name not in before_modules
        ],
        "page_loaded": True,
    }
    if args.screenshot:
        # 加载完成与合成帧就绪不同；仅截图等待绘制，不计入性能指标。
        paint_loop = QEventLoop()
        QTimer.singleShot(250, paint_loop.quit)
        paint_loop.exec()
        target = Path(args.screenshot).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if not stack.grab().save(str(target)):
            raise RuntimeError("面板截图保存失败")
    print(MARKER + json.dumps(data, ensure_ascii=False), flush=True)
    stack.close()
    # 测量进程一次一用，避免 Chromium 清理阶段影响下一次样本的计时。
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--baseline-ref", help="如 HEAD，仅在子进程读取历史源码")
    parser.add_argument("--output", type=Path, required=False)
    parser.add_argument("--screenshot", help="保存当前源码第一次样本的离屏 Qt 截图")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-ref", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        _measure_child(args)
        return
    if not 1 <= args.repeat <= 20:
        parser.error("--repeat 必须在 1 到 20 之间")
    baseline = None
    if args.baseline_ref:
        baseline = subprocess.check_output(
            ["git", "rev-parse", "--verify", args.baseline_ref + "^{commit}"], cwd=ROOT,
        ).decode().strip()
    report = {
        "scenario": "明渠首页就绪后，首次进入有压管道直到真实网页加载完成",
        "environment": "独立 Python 进程，Qt offscreen，真实 WebEngine，1380x850",
        "python": sys.version,
        "baseline_ref": baseline,
        "source_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in SOURCE_MODULES.values()
        },
        "samples": {},
        "medians_ms": {},
    }
    groups = [("baseline", baseline), ("current", None)] if baseline else [("current", None)]
    for label, ref in groups:
        samples = []
        for index in range(args.repeat):
            command = [sys.executable, str(Path(__file__).resolve()), "--child"]
            if ref:
                command += ["--source-ref", ref]
            if label == "current" and index == 0 and args.screenshot:
                command += ["--screenshot", args.screenshot]
            child = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
            lines = [line[len(MARKER):] for line in child.stdout.splitlines() if line.startswith(MARKER)]
            if child.returncode or not lines:
                raise RuntimeError(child.stdout + child.stderr)
            sample = json.loads(lines[-1])
            samples.append(sample)
            print(f"{label} {index + 1}/{args.repeat}: {sample['first_entry_ms']:.1f} ms", flush=True)
        report["samples"][label] = samples
        report["medians_ms"][label] = {
            name: round(statistics.median(sample[name] for sample in samples), 3)
            for name in ("import_ms", "construction_ms", "display_ready_ms", "first_entry_ms", "repeat_switch_ms")
        }
    if baseline:
        old = report["medians_ms"]["baseline"]["first_entry_ms"]
        new = report["medians_ms"]["current"]["first_entry_ms"]
        report["first_entry_reduction_percent"] = round((old - new) / old * 100, 2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["medians_ms"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
