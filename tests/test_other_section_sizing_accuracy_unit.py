# -*- coding: utf-8 -*-
"""用优化前的完整成果及独立几何输出验证提速不改变结果。"""

import json
import math
from pathlib import Path
import random
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.benchmark_other_section_sizing import KERNEL_DIR, call_case, load_kernels

REFERENCE = json.loads(
    (ROOT / "docs/diagnostics/other_section_sizing_benchmark_20261004.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def kernels():
    return load_kernels(KERNEL_DIR)


@pytest.mark.parametrize("case", REFERENCE["comparisons"], ids=lambda case: case["case"])
def test_complete_result_matches_preoptimization_snapshot(kernels, case):
    """比较全部原始字段，涵盖尺寸、水深、净空、状态及失败文案。"""
    assert call_case(kernels, case) == case["baseline_result"]


@pytest.mark.parametrize("theta_deg", [90.0, 120.0, 150.0, 180.0])
def test_fast_arch_flow_matches_original_outputs_at_geometry_boundaries(kernels, theta_deg):
    """直墙与拱部交界、近满流及随机水深均使用原几何函数作为独立参照。"""
    tunnel = kernels["隧洞设计"]
    rng = random.Random(20261004)
    theta = math.radians(theta_deg)
    for width in (0.2, 1.8, 5.0, 20.0):
        arch = (width / 2) / math.sin(theta / 2) * (1 - math.cos(theta / 2))
        for wall in (0.0, 0.4, 3.0):
            height = arch + wall
            depths = [0.0, 1e-10, 1e-5, wall - 1e-10, wall, wall + 1e-10,
                      height - 1e-10, height, height + 1.0]
            depths += [rng.uniform(0, height) for _ in range(10)]
            flow = tunnel._make_horseshoe_flow_evaluator(width, height, theta, 0.014, 0.001)
            for depth in depths:
                assert flow(depth) == tunnel.calculate_horseshoe_outputs(
                    width, height, theta, depth, 0.014, 0.001)["Q"]


def test_arch_area_pruning_keeps_fine_grid_before_first_valid_coarse_height(kernels, monkeypatch):
    """当前粗点面积偏大时，前一粗点与当前粗点之间仍可能存在更优细点。"""
    culvert = kernels["圆拱直墙型暗涵设计"]
    tunnel = kernels["隧洞设计"]
    theta = math.pi

    def candidate(width, height, *args):
        if height < 0.61:
            return None
        return {"A_total": tunnel.calculate_horseshoe_total_area(width, height, theta)}

    monkeypatch.setattr(culvert, "_calc_arch_height", lambda *args: 0.49)
    monkeypatch.setattr(culvert, "_check_candidate", candidate)
    args = (1.0, theta, 5.0, 6.0, 0.014, 0.001, 0.1, 5.0, True)
    full_scan = culvert._search_min_height_for_width(*args)
    limit = tunnel.calculate_horseshoe_total_area(1.0, 0.62, theta)
    pruned_scan = culvert._search_min_height_for_width(*args, area_limit=limit)
    assert pruned_scan == full_scan
    assert pruned_scan[0] == pytest.approx(0.61)
    assert pruned_scan[1]["A_total"] < limit


def test_arch_area_pruning_keeps_equal_and_roundoff_boundary(kernels):
    tunnel = kernels["隧洞设计"]
    area = tunnel.calculate_horseshoe_total_area(2.0, 3.0, math.pi)
    assert not tunnel._horseshoe_area_cannot_improve(2.0, 3.0, math.pi, area)
    assert not tunnel._horseshoe_area_cannot_improve(2.0, 3.0, math.pi, area - 1e-10)
    assert tunnel._horseshoe_area_cannot_improve(2.0, 3.0, math.pi, area - 1e-7)
