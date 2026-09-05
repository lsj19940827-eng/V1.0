# -*- coding: utf-8 -*-
"""验证 PE 规范规格与有压管道水力计算、推荐和批量输出的集成。"""

import math
import shutil
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from calc_渠系计算算法内核.pe_pipe_catalog import get_pe_pipe_specs
from calc_渠系计算算法内核.有压管道设计 import (
    BatchScanConfig,
    PressurePipeInput,
    recommend_diameter,
    run_batch_scan,
)


@pytest.fixture
def local_tmp_path():
    """在仓库内创建独立临时目录，避开部分 Windows 环境的 pytest ACL 问题。"""
    base_dir = Path(__file__).resolve().parents[1] / ".pytest_pressure_pipe_pe"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = base_dir / f"pe_integration_{uuid.uuid4().hex}"
    temp_dir.mkdir()
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_pe_recommendation_uses_inner_diameter_and_smallest_compliant_dn():
    """PE 候选应以表列 DN/en 得到 di，并在多个经济候选中取最小 DN。"""
    result = recommend_diameter(
        PressurePipeInput(
            Q=0.5,
            material_key="HDPE管",
            pe_material_grade="PE100",
            pe_nominal_pressure_mpa=1.0,
        )
    )

    candidate = result.recommended
    assert candidate is not None
    assert candidate.nominal_outer_diameter_mm == 800
    assert candidate.nominal_wall_thickness_mm == pytest.approx(47.4)
    assert candidate.hydraulic_inner_diameter_mm == pytest.approx(705.2)
    assert candidate.D == pytest.approx(0.7052)
    assert candidate.V_press == pytest.approx(0.5 / (math.pi * 0.7052 ** 2 / 4.0))

    economic_dns = [
        item.nominal_outer_diameter_mm
        for item in result.top_candidates
        if item.category == "经济"
    ]
    assert len(economic_dns) >= 2
    assert candidate.nominal_outer_diameter_mm == min(economic_dns)


def test_pe_manual_selection_accepts_only_standard_dn_for_selected_series():
    """指定 PE 外径应从所选等级和 PN 的合法表列规格中精确匹配。"""
    result = recommend_diameter(
        PressurePipeInput(
            Q=0.1,
            material_key="HDPE管",
            pe_material_grade="PE100",
            pe_nominal_pressure_mpa=1.0,
            manual_nominal_diameter_mm=355,
        )
    )

    candidate = result.recommended
    assert result.category == "指定"
    assert candidate is not None
    assert candidate.nominal_outer_diameter_mm == 355
    assert candidate.nominal_wall_thickness_mm == pytest.approx(21.1)
    assert candidate.hydraulic_inner_diameter_mm == pytest.approx(312.8)
    assert "GB/T 13663.2-2018" in result.calc_steps
    assert "di = DN - 2en" in result.calc_steps

    with pytest.raises(ValueError, match="不是.*标准公称外径.*可选 DN"):
        recommend_diameter(
            PressurePipeInput(
                Q=0.1,
                material_key="HDPE管",
                manual_nominal_diameter_mm=350,
            )
        )

    for invalid_dn in (0, -315, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="可选 DN"):
            recommend_diameter(
                PressurePipeInput(
                    Q=0.1,
                    material_key="HDPE管",
                    manual_nominal_diameter_mm=invalid_dn,
                )
            )


@pytest.mark.parametrize(
    ("legacy_inner_diameter_m", "expected_dn", "expected_inner_diameter_mm"),
    [
        (0.6, 710, 625.8),
        (0.8, 1000, 881.4),
    ],
)
def test_legacy_pe_manual_inner_diameter_is_safely_rounded_up(
    legacy_inner_diameter_m,
    expected_dn,
    expected_inner_diameter_mm,
):
    """旧项目水力内径应安全上取规格，不能被静默改解释为同数值公称外径。"""
    result = recommend_diameter(
        PressurePipeInput(
            Q=0.5,
            material_key="HDPE管",
            manual_D=legacy_inner_diameter_m,
        )
    )

    candidate = result.recommended
    assert result.category == "指定"
    assert candidate is not None
    assert candidate.nominal_outer_diameter_mm == expected_dn
    assert candidate.hydraulic_inner_diameter_mm == pytest.approx(expected_inner_diameter_mm)
    assert candidate.D >= legacy_inner_diameter_m
    assert any("旧版水力内径" in flag and "安全上取" in flag for flag in candidate.flags)
    assert "旧项目规格迁移" in result.reason
    assert "旧项目迁移" in result.calc_steps


def test_pe_process_uses_exact_decimal_inner_diameter_in_loss_substitution():
    """PE 详细计算式应显示实际 312.8 mm，不能展示四舍五入后的 313 mm。"""
    result = recommend_diameter(
        PressurePipeInput(
            Q=0.1,
            material_key="HDPE管",
            manual_nominal_diameter_mm=355,
        )
    )

    assert "((312.8)^{4.77})" in result.calc_steps
    assert "((313)^{4.77})" not in result.calc_steps


def test_pe_batch_catalog_mode_exports_costing_and_hydraulic_dimensions(local_tmp_path):
    """生产批量模式应遍历 PE 目录并同时导出造价规格和水力内径。"""
    specs = get_pe_pipe_specs("PE100", 1.0)
    result = run_batch_scan(
        BatchScanConfig(
            q_values=np.array([0.1]),
            slope_denominators=[],
            diameter_values=None,
            materials=["HDPE管"],
            output_dir=str(local_tmp_path),
            output_pdf_charts=False,
            output_merged_pdf=False,
            output_subplot_png=False,
            pe_material_grade="PE100",
            pe_nominal_pressure_mpa=1.0,
        )
    )

    frame = pd.read_csv(result.csv_path)
    assert len(frame) == len(specs)
    assert set(frame["管材类型"]) == {"HDPE管"}
    required_columns = {
        "公称外径 DN (mm)",
        "公称壁厚 en (mm)",
        "水力计算内径 di (mm)",
        "PE材料等级",
        "PE公称压力 PN (MPa)",
        "PE标准尺寸比 SDR",
        "产品标准",
    }
    assert required_columns.issubset(frame.columns)

    row = frame.loc[frame["公称外径 DN (mm)"] == 315].iloc[0]
    assert row["公称壁厚 en (mm)"] == pytest.approx(18.7)
    assert row["水力计算内径 di (mm)"] == pytest.approx(277.6)
    assert row["D (m)"] == pytest.approx(0.2776)
    assert row["PE材料等级"] == "PE100"
    assert row["PE标准尺寸比 SDR"] == pytest.approx(17.0)
