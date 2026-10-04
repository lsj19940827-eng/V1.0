# -*- coding: utf-8 -*-
"""比较渡槽搜索结果与耗时，支持传入修复后未优化的内核文件。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import random
import statistics
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / 'calc_渠系计算算法内核' / '渡槽设计.py'


def load_kernel(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def comparison_cases():
    """固定种子覆盖不同流量、糙率、坡降、流速约束、加大比例和拉杆。"""
    rng = random.Random(20261004)
    cases = []
    for kind in ('u', 'rect'):
        for index in range(90):
            params = dict(
                Q=10 ** rng.uniform(-1.3, 2.4), n=rng.choice([0.011, 0.014, 0.017, 0.025]),
                slope_inv=rng.choice([500, 1500, 2000, 5000, 12000]),
                v_min=rng.choice([0.1, 0.6, 1.0]), v_max=rng.choice([1.3, 2.0, 3.0, 100.0]),
                manual_increase_percent=rng.choice([0, 10, 20, 30, 18.2468]),
                tie_rod_height=rng.choice([0.0, 0.05, 0.3, 0.7]),
            )
            if kind == 'rect':
                params['depth_width_ratio'] = rng.choice([0.6, 0.8, 1.0, 1.5])
                params['chamfer_angle'] = rng.choice([0, 30, 45, 60])
                params['chamfer_length'] = rng.choice([0.0, 0.15, 0.25, 0.4])
                if index % 10 == 0:
                    params['manual_B'] = rng.choice([1.5, 3.0, 5.0])
            elif index % 10 == 0:
                params['manual_R'] = rng.choice([0.5, 1.33, 2.4, 4.0])
            cases.append((f'{kind}_{index:03}', kind, params))
    # 搜索边界、近零流量、大流量及无法满足流速约束的情况。
    for kind in ('u', 'rect'):
        for q in (0.00001, 0.01, 5.0, 100.0, 2000.0, 100000.0):
            for inc in (0, 30):
                cases.append((f'{kind}_edge_{q}_{inc}', kind, dict(
                    Q=q, n=0.014, slope_inv=2000, v_min=0.1, v_max=100,
                    manual_increase_percent=inc,
                )))
    return cases


def timing_cases():
    cases = []
    for kind in ('u', 'rect'):
        for q in (1.0, 5.0, 20.0, 100.0):
            params = dict(Q=q, n=0.014, slope_inv=2000, v_min=0.1, v_max=100,
                          manual_increase_percent=20, tie_rod_height=0.3)
            cases.append((f'{kind}_Q{q:g}', kind, params))
        cases.append((f'{kind}_velocity_limit', kind, dict(
            Q=5.0, n=0.014, slope_inv=2000, v_min=0.1, v_max=1.3, manual_increase_percent=30,
        )))
    cases.append(('rect_chamfer', 'rect', dict(Q=20, n=0.014, slope_inv=3000, v_min=0.1,
                  v_max=100, chamfer_angle=45, chamfer_length=0.2, manual_increase_percent=20)))
    return cases


def compare(reference, candidate, cases):
    failures = []
    success_count = 0
    for label, kind, params in cases:
        old = getattr(reference, 'quick_calculate_' + kind)(**params)
        new = getattr(candidate, 'quick_calculate_' + kind)(**params)
        success_count += bool(new['success'])
        # 比较完整结果字典，包含尺寸、水深、流速、超高、状态和提示文案。
        if old != new:
            changed = {key: [old.get(key), new.get(key)] for key in old.keys() | new.keys()
                       if old.get(key) != new.get(key)}
            failures.append(dict(case=label, params=params, differences=changed))
    return dict(cases=len(cases), successes=success_count, exact_matches=len(cases)-len(failures),
                failures=failures)


def benchmark(reference, candidate, repeats):
    rows = []
    for label, kind, params in timing_cases():
        functions = [getattr(reference, 'quick_calculate_' + kind),
                     getattr(candidate, 'quick_calculate_' + kind)]
        for function in functions:
            function(**params)
        samples = [[], []]
        for repeat in range(repeats):
            # 交替执行顺序，减小热机和系统短时负载差异。
            for index in (0, 1) if repeat % 2 == 0 else (1, 0):
                start = time.perf_counter()
                result = functions[index](**params)
                samples[index].append((time.perf_counter() - start) * 1000)
        before, after = (statistics.median(values) for values in samples)
        rows.append(dict(case=label, params=params, success=result['success'],
                         baseline_ms=before, optimized_ms=after, speedup=before/after,
                         samples_ms=samples))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, help='未优化内核；省略时关闭当前内核的剪枝和缓存作为参照')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--original-reference', type=Path, help='修复前内核；仅用于额外记录旧版本耗时与结果变化')
    parser.add_argument('--repeats', type=int, default=7)
    args = parser.parse_args()
    candidate = load_kernel(KERNEL, 'aqueduct_optimized')
    reference = load_kernel(args.reference or KERNEL, 'aqueduct_reference')
    if args.reference is None:
        reference._u_area_lower_bound = lambda radius: -float('inf')
        reference._rect_search_start = lambda *args: 50
        reference.lru_cache = lambda **kwargs: lambda function: function
    cases = comparison_cases() + timing_cases()
    report = dict(
        python=platform.python_version(), platform=platform.platform(),
        baseline='修复后的完整厘米格点搜索；水深求解器、取整、约束与目标函数相同',
        reference_sha256=hashlib.sha256((args.reference or KERNEL).read_bytes()).hexdigest(),
        optimized_sha256=hashlib.sha256(KERNEL.read_bytes()).hexdigest(),
        accuracy=compare(reference, candidate, cases), repeats=args.repeats,
        timings=benchmark(reference, candidate, args.repeats),
    )
    if args.original_reference is not None:
        original = load_kernel(args.original_reference, 'aqueduct_original')
        report['original_sha256'] = hashlib.sha256(args.original_reference.read_bytes()).hexdigest()
        report['timings_original'] = benchmark(original, candidate, args.repeats)
        report['original_common_result_comparison'] = []
        for label, kind, params in timing_cases():
            old = getattr(original, 'quick_calculate_' + kind)(**params)
            new = getattr(candidate, 'quick_calculate_' + kind)(**params)
            changed = {key: [old[key], new.get(key)] for key in old if old[key] != new.get(key)}
            report['original_common_result_comparison'].append(dict(case=label, differences=changed))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(accuracy=report['accuracy'], timings=[{
        key: row[key] for key in ('case', 'baseline_ms', 'optimized_ms', 'speedup')
    } for row in report['timings']]), ensure_ascii=False, indent=2))
    return 1 if report['accuracy']['failures'] else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
