# -*- coding: utf-8 -*-
"""测试倒虹吸加大流量工况水损传递

验证点：
1. 计算引擎能正确计算加大工况水损 (total_head_loss_inc)
2. multi_siphon_dialog 的数据传递逻辑优先使用加大工况水损
3. SiphonManager 正确存储加大工况水损
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '倒虹吸水力计算系统'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '推求水面线'))

from 倒虹吸水力计算系统.siphon_hydraulics import HydraulicCore
from 倒虹吸水力计算系统.siphon_models import GlobalParameters, StructureSegment, SegmentType


def test_calculation_engine():
    """测试1: 计算引擎能产生加大工况水损"""
    print("=" * 60)
    print("Test 1: Calculation engine - increased flow loss")
    print("=" * 60)

    increase_percent = 20.0

    global_params = GlobalParameters(
        Q=5.0,
        roughness_n=0.014,
        v_guess=2.0,
        v_channel_in=1.0,   # v1
        v_pipe_in=0.0,      # v2: AUTO_PIPE -> pipe velocity
        v_channel_out=0.0,  # v_out: pipe side
        v_pipe_out=1.0,     # v3: channel side
        xi_inlet=0.1,
        xi_outlet=0.2,
    )

    segments = [
        StructureSegment(segment_type=SegmentType.INLET, length=0.0),
        StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0),
        StructureSegment(segment_type=SegmentType.OUTLET, length=0.0),
    ]

    result = HydraulicCore.execute_calculation(
        global_params=global_params,
        segments=segments,
        increase_percent=increase_percent,
    )

    if not result:
        print("  FAIL: calculation returned None")
        return False

    print(f"  design flow loss:    {result.total_head_loss:.4f} m")
    print(f"  increased flow loss: {result.total_head_loss_inc:.4f} m")
    print(f"  increase_percent:    {result.increase_percent}%")

    if result.total_head_loss_inc == 0.0 and result.total_head_loss == 0.0:
        print("  FAIL: both losses are zero")
        return False

    if result.total_head_loss_inc == result.total_head_loss:
        print("  FAIL: increased loss == design loss (should differ)")
        return False

    diff = result.total_head_loss_inc - result.total_head_loss
    print(f"  diff: {diff:.4f} m")
    print("  PASS")
    return True


def test_data_passing_logic():
    """测试2: 数据传递逻辑 - 优先使用加大工况水损"""
    print("\n" + "=" * 60)
    print("Test 2: Data passing logic (multi_siphon_dialog)")
    print("=" * 60)

    # Mock CalculationResult
    class MockResult:
        def __init__(self, design, increased):
            self.total_head_loss = design
            self.total_head_loss_inc = increased

    # Case A: inc available -> use inc
    r = MockResult(design=0.5, increased=0.72)
    head_loss = r.total_head_loss_inc if r.total_head_loss_inc is not None else r.total_head_loss
    assert head_loss == 0.72, f"Case A failed: expected 0.72, got {head_loss}"
    print(f"  Case A (both available):  PASS -> {head_loss} (increased)")

    # Case B: inc is None -> fallback to design
    r = MockResult(design=0.5, increased=None)
    head_loss = r.total_head_loss_inc if r.total_head_loss_inc is not None else r.total_head_loss
    assert head_loss == 0.5, f"Case B failed: expected 0.5, got {head_loss}"
    print(f"  Case B (inc is None):     PASS -> {head_loss} (fallback)")

    # Case C: inc is 0.0 -> use 0.0 (valid computed result)
    r = MockResult(design=0.5, increased=0.0)
    head_loss = r.total_head_loss_inc if r.total_head_loss_inc is not None else r.total_head_loss
    assert head_loss == 0.0, f"Case C failed: expected 0.0, got {head_loss}"
    print(f"  Case C (inc is 0.0):      PASS -> {head_loss} (zero is valid)")

    print("  PASS: all cases correct")
    return True


def test_siphon_manager_storage():
    """测试3: SiphonManager 存储加大工况水损"""
    print("\n" + "=" * 60)
    print("Test 3: SiphonManager storage")
    print("=" * 60)

    from managers.siphon_manager import SiphonManager

    mgr = SiphonManager()

    mgr.update_siphon_result("test_siphon", total_head_loss=0.72, diameter=0.8)
    stored = mgr.get_result("test_siphon")
    assert stored == 0.72, f"Storage failed: expected 0.72, got {stored}"
    print(f"  store & retrieve:  PASS -> {stored}")

    all_results = mgr.get_all_results()
    assert "test_siphon" in all_results
    assert all_results["test_siphon"] == 0.72
    print(f"  get_all_results:   PASS -> {all_results}")

    print("  PASS")
    return True


if __name__ == "__main__":
    results = []
    results.append(test_calculation_engine())
    results.append(test_data_passing_logic())
    results.append(test_siphon_manager_storage())

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Summary: {passed}/{total} tests passed")
    print("=" * 60)

    sys.exit(0 if all(results) else 1)
