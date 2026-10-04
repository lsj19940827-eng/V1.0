# -*- coding: utf-8 -*-
"""复核隧洞、暗涵选型的完整结果与耗时；参照可使用优化前内核或已保存成果。"""

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import random
import statistics
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
KERNEL_DIR = ROOT / "calc_渠系计算算法内核"
MODULE_NAMES = ("隧洞设计", "矩形暗涵设计", "圆拱直墙型暗涵设计")
FUNCTIONS = {
    "arch_tunnel": ("隧洞设计", "quick_calculate_horseshoe"),
    "arch_culvert": ("圆拱直墙型暗涵设计", "quick_calculate_arch_culvert"),
    "rect_culvert": ("矩形暗涵设计", "quick_calculate_rectangular_culvert"),
}


def load_kernels(directory):
    """隔离加载整组内核，保证参照拱涵绑定参照隧洞，避免混入优化后求解器。"""
    saved = {name: sys.modules.get(name) for name in MODULE_NAMES}
    modules = {}
    try:
        for name in MODULE_NAMES:
            spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            modules[name] = module
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return modules


def call_case(modules, case):
    name, function = FUNCTIONS[case["kind"]]
    return getattr(modules[name], function)(**case["params"])


def comparison_cases():
    """覆盖自动、固定宽度、固定几何、不同约束及粗细搜索交界。"""
    common = dict(Q=5.0, n=0.014, slope_inv=1000.0, v_min=0.1, v_max=5.0)
    cases = []

    def add(label, kind, timing=False, **params):
        cases.append(dict(case=label, kind=kind, params=dict(common, **params), timing=timing))

    for kind in ("arch_tunnel", "arch_culvert"):
        add(f"{kind}_Q5", kind, timing=True)
        add(f"{kind}_Q30", kind, timing=True, Q=30.0, theta_deg=120.0,
            manual_increase_percent=25.0)
        add(f"{kind}_low", kind, Q=0.5, theta_deg=90.0, manual_increase_percent=0.0)
        add(f"{kind}_high", kind, Q=100.0, theta_deg=150.0, slope_inv=3000.0)
        add(f"{kind}_velocity_limit", kind, v_max=1.2, theta_deg=120.0,
            manual_increase_percent=30.0)
        add(f"{kind}_no_solution", kind, v_min=6.0, v_max=7.0)
        for width in (0.2, 1.8, 2.4, 5.0):
            add(f"{kind}_width_{width}", kind, manual_B=width, theta_deg=150.0)
        for wall in (0.0, 0.5, 1.5, 3.0):
            add(f"{kind}_wall_{wall}", kind, manual_B=3.0, manual_H_straight=wall)
        for height in (2.999, 3.0, 3.001):
            add(f"{kind}_height_{height}", kind, Q=6.0, manual_B=3.0,
                manual_H_straight=height - 1.5, manual_increase_percent=0.0)

    for ratio in (0.4, 0.8, 1.2, 1.8):
        for inc in (0.0, 30.0):
            add(f"rect_HB_{ratio}_inc{inc}", "rect_culvert", target_HB_ratio=ratio,
                manual_increase_percent=inc)
    add("rect_HB_Q5", "rect_culvert", timing=True, target_HB_ratio=1.2)
    add("rect_HB_Q30", "rect_culvert", timing=True, Q=30.0, target_HB_ratio=1.2)
    add("rect_HB_no_solution", "rect_culvert", target_HB_ratio=1.2, v_min=6.0, v_max=7.0)
    for ratio in (0.5, 1.5, 2.5):
        add(f"rect_Bh_{ratio}", "rect_culvert", timing=ratio == 1.5, target_BH_ratio=ratio)
    for inc in (0.0, 30.0):
        add(f"rect_Bh_inc{inc}", "rect_culvert", target_BH_ratio=1.5,
            manual_increase_percent=inc)
    for q in (5.0, 30.0, 100.0):
        add(f"rect_economic_{q}", "rect_culvert", Q=q)
    for width in (0.2, 1.8, 2.4, 5.0):
        add(f"rect_width_{width}", "rect_culvert", manual_B=width)
        add(f"rect_fixed_{width}", "rect_culvert", manual_B=width, manual_H=3.0)
    return cases


def check_solvers(reference, candidate, count=3000):
    """同一随机输入比较原始水深及成功标记，不用舍入值或容差掩盖差异。"""
    rng = random.Random(20261004)
    comparisons = 0
    failures = []
    for index in range(count):
        width = rng.uniform(0.1, 20.0)
        height = rng.uniform(0.05, 25.0)
        theta = math.radians(rng.choice((1e-8, 30, 90, 120, 150, 180)))
        n = rng.uniform(0.008, 0.05)
        slope = rng.choice((0.0, 1 / 10000, 1 / 1000, 1 / 100))
        q = 10 ** rng.uniform(-8, 4)
        for name, function, args in (
            ("隧洞设计", "solve_water_depth_horseshoe", (width, height, theta, n, slope, q)),
            ("矩形暗涵设计", "solve_water_depth_rectangular", (width, height, n, slope, q)),
        ):
            old = getattr(reference[name], function)(*args)
            new = getattr(candidate[name], function)(*args)
            comparisons += 1
            if old != new:
                failures.append(dict(index=index, function=function, args=args, baseline=old, optimized=new))
    return dict(cases=comparisons, exact_matches=comparisons - len(failures), failures=failures)


def benchmark_case(reference, candidate, case, repeats):
    """预热后交替运行，保留所有计时样本，以中位数比较。"""
    modules = (reference, candidate) if reference is not None else (candidate,)
    samples = [[] for _ in modules]
    for module_set in modules:
        call_case(module_set, case)
    for repeat in range(repeats):
        indices = range(len(modules)) if repeat % 2 == 0 else reversed(range(len(modules)))
        for index in indices:
            start = time.perf_counter()
            call_case(modules[index], case)
            samples[index].append((time.perf_counter() - start) * 1000)
    row = dict(case=case["case"], params=case["params"], optimized_ms=statistics.median(samples[-1]),
               optimized_samples_ms=samples[-1])
    if reference is not None:
        row.update(baseline_ms=statistics.median(samples[0]), baseline_samples_ms=samples[0])
        row["speedup"] = row["baseline_ms"] / row["optimized_ms"]
    return row


def file_hashes(directory):
    return {name: hashlib.sha256((directory / f"{name}.py").read_bytes()).hexdigest()
            for name in MODULE_NAMES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--reference-dir", type=Path, help="优化前三个内核文件的目录")
    source.add_argument("--reference-results", type=Path, help="以已保存的完整成果复核当前代码；不重新比较旧耗时")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("重复次数必须至少为1")
    sys.stdout.reconfigure(encoding="utf-8")
    candidate = load_kernels(KERNEL_DIR)
    reference = load_kernels(args.reference_dir) if args.reference_dir else None
    previous = json.loads(args.reference_results.read_text(encoding="utf-8")) if args.reference_results else None
    expected_rows = {row["case"]: row for row in previous["comparisons"]} if previous else {}
    cases = comparison_cases() if previous is None else [
        {key: row[key] for key in ("case", "kind", "params", "timing")} for row in previous["comparisons"]
    ]
    report = dict(python=platform.python_version(), platform=platform.platform(), repeats=args.repeats,
                  baseline="本轮优化前的在盘代码，已包含前一轮拱涵净空修复",
                  reference_sha256=file_hashes(args.reference_dir) if reference else previous["reference_sha256"],
                  optimized_sha256=file_hashes(KERNEL_DIR), comparisons=[], timings=[])
    if reference:
        report["solver_accuracy"] = check_solvers(reference, candidate)
        print("水深求解对照", report["solver_accuracy"], flush=True)
    failures = []
    for index, case in enumerate(cases, 1):
        old = call_case(reference, case) if reference else expected_rows[case["case"]]["baseline_result"]
        new = call_case(candidate, case)
        changed = {key: [old.get(key), new.get(key)] for key in old.keys() | new.keys()
                   if old.get(key) != new.get(key)}
        exact = old == new
        if not exact:
            failures.append(dict(case=case["case"], differences=changed))
        report["comparisons"].append(dict(case, baseline_result=old, exact_match=exact, differences=changed))
        print(f"{index}/{len(cases)} {case['case']}: {'一致' if exact else '差异'}", flush=True)
    report["accuracy"] = dict(cases=len(cases), exact_matches=len(cases)-len(failures), failures=failures,
                              successes=sum(row["baseline_result"]["success"] for row in report["comparisons"]))
    if not failures:
        for case in cases:
            if case["timing"]:
                row = benchmark_case(reference, candidate, case, args.repeats)
                report["timings"].append(row)
                print("计时", json.dumps(row, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if failures or report.get("solver_accuracy", {}).get("failures") else 0


if __name__ == "__main__":
    raise SystemExit(main())
