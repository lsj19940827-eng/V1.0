"""无压导出默认规格的工况与净空边界、最小性和失败保留回归。"""

import copy


import pytest

from calc_渠系计算算法内核.unpressurized_comparison import preferred_diameter
from calc_渠系计算算法内核.unpressurized_selection import row_verdict, selection_summary


@pytest.fixture
def rows():
    """小管全失败，中管仅设计陡坡可解，大管两工况两底坡均可解。"""
    result = []
    for diameter in (.4, .8, 1.2):
        for slope in (500, 3000):
            for basis, flow in (("设计流量", .2), ("加大流量", .26)):
                passed = diameter == 1.2 or (diameter == .8 and slope == 500 and basis == "设计流量")
                result.append(dict(material="测试管材", specification=f"测试规格 {diameter:g} m",
                    diameter=diameter, denominator=slope, basis=basis, flow=flow, design_flow=.2,
                    roughness=.014, category="经济" if diameter == .4 else "兜底",
                    status="可形成均匀流" if passed else "能力不足", depth=.25 if passed else None,
                    filling=.25 / diameter if passed else None, velocity=1.0 if passed else None,
                    capacity=.5 if passed else .1, clearance_height=diameter - .25 if passed else None,
                    clearance_area=40 if passed else None, height_limit=None, area_limit=None,
                    pressure_velocity=1.5, pressure_loss=2.0, criteria="未设置净空判据",
                    reason="" if passed else "超过圆管模型最大无压流量"))
    return result


def test_per_slope_minimum_and_both_conditions(rows):
    """两个工况默认均须满足，切换仅设计时才允许选更小规格。"""
    original = copy.deepcopy(rows)
    assert [r["diameter"] for r in selection_summary(rows)["summaries"]] == [1.2, 1.2]
    assert [r["diameter"] for r in selection_summary(rows, both=False)["summaries"]] == [.8, 1.2]
    assert preferred_diameter(rows) == 1.2
    assert rows == original


def test_clearance_threshold_equality_and_missing_fields(rows):
    """净空恰等于阈值可用，稍低或条件结果缺失不可用。"""
    row = copy.deepcopy(rows[-1])
    row.update(height_limit=.95, clearance_height=.95, area_limit=40)
    assert row_verdict(row) == (True, "满足所设条件")
    row["clearance_area"] = 39.99
    assert row_verdict(row) == (False, "净空面积不足")
    row["clearance_area"] = None
    assert "待核查" in row_verdict(row)[1]
    row["depth"] = float("nan")
    assert not row_verdict(row)[0]


def test_missing_and_solver_failures_do_not_confirm_minimality(rows):
    """较小规格的求解失败和缺工况须保留，不能断言较大规格严格最小。"""
    smaller = next(r for r in rows if r["diameter"] == .8 and r["denominator"] == 500 and r["basis"] == "加大流量")
    smaller.update(status="求解失败", reason="残差超限")
    report = selection_summary(rows)
    assert report["summaries"][0]["pending_smaller"]
    rows.remove(smaller)
    report = selection_summary(rows)
    assert report["summaries"][0]["pending_smaller"]
    assert "缺少工况" in report["cells"][(.8, 500)]["label"]


def test_no_solution_and_no_increase(rows):
    """全不可用保留扫描上限原因，没有加大结果时按设计工况筛选。"""
    failed = [r for r in rows if r["diameter"] == .4]
    report = selection_summary(failed)
    assert all(r["diameter"] is None and r["reference"] == .4 for r in report["summaries"])
    design = [r for r in rows if r["basis"] == "设计流量"]
    assert not selection_summary(design)["increased"]
    assert selection_summary(design)["summaries"][0]["diameter"] == .8


def test_project_condition_can_reject_every_model_solution(rows):
    """即使能力足够，净空高度和面积约束仍能使整个扫描范围不可用。"""
    for row in rows:
        row.update(height_limit=1.0, area_limit=50)
    report = selection_summary(rows)
    assert all(item["diameter"] is None for item in report["summaries"])
    assert "净空高度不足" in report["cells"][(1.2, 500)]["label"]
    assert "净空面积不足" in report["cells"][(1.2, 500)]["label"]


def test_incomplete_grid_is_retained_as_pending(rows):
    """缺少整个管径底坡组合时仍显示待核查，不把其标成能力不足。"""
    rows = [r for r in rows if not (r["diameter"] == .8 and r["denominator"] == 3000)]
    report = selection_summary(rows)
    assert report["summaries"][1]["pending"]
    assert report["summaries"][1]["pending_smaller"]
    assert "缺少工况" in report["cells"][(.8, 3000)]["label"]
