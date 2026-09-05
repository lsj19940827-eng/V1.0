# -*- coding: utf-8 -*-
"""验证 DI、PCCP、FRPM 产品规格目录与有压管道内核的集成。"""

import math
import shutil
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from calc_渠系计算算法内核.pipe_product_catalog import (
    FRPM_INNER_SERIES_DIAMETERS_MM,
    get_pipe_product_spec,
)
from calc_渠系计算算法内核.有压管道设计 import (
    BatchScanConfig,
    PressurePipeInput,
    evaluate_single_diameter,
    recommend_diameter,
    run_batch_scan,
)


@pytest.fixture
def local_tmp_path():
    """在仓库内创建独立临时目录，避开部分 Windows 环境的临时目录权限问题。"""
    base_dir = Path(__file__).resolve().parents[1] / ".pytest_pressure_pipe_catalog"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = base_dir / f"catalog_integration_{uuid.uuid4().hex}"
    temp_dir.mkdir()
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_di_manual_product_size_uses_derived_inner_diameter_and_metadata() -> None:
    """DI 指定 DN 应用 DE、壁厚和内衬换算内径，并完整带入候选结果。"""
    result = recommend_diameter(PressurePipeInput(
        Q=0.1,
        material_key="球墨铸铁管",
        manual_product_diameter_mm=300,
        ductile_iron_class="PREFERRED",
    ))

    candidate = result.recommended
    assert result.category == "指定"
    assert candidate is not None
    assert candidate.product_family == "DI"
    assert candidate.product_spec_id == "DI|GB13295-2026|C40|CML|DN300"
    assert candidate.nominal_symbol == "DN"
    assert candidate.nominal_diameter_mm == 300
    assert candidate.outer_diameter_mm == pytest.approx(326.0)
    assert candidate.nominal_wall_thickness_mm == pytest.approx(6.2)
    assert candidate.class_code == "C40"
    assert candidate.lining_code == "CML"
    assert candidate.lining_thickness_mm == pytest.approx(4.0)
    assert candidate.hydraulic_inner_diameter_mm == pytest.approx(305.6)
    assert candidate.D == pytest.approx(0.3056)
    assert candidate.V_press == pytest.approx(0.1 / (math.pi * 0.3056 ** 2 / 4.0))
    assert "GB/T 17457—2019" in candidate.product_standard_references
    assert "GB/T 13295—2026" in candidate.product_standard_references


def test_di_batch_csv_separates_pe_and_general_wall_thickness_columns(local_tmp_path) -> None:
    """DI 壁厚应进入通用产品列，不能误填为 PE 专用的 en。"""
    result = run_batch_scan(BatchScanConfig(
        q_values=np.array([0.1]),
        slope_denominators=[],
        diameter_values=None,
        materials=["球墨铸铁管"],
        output_dir=str(local_tmp_path),
        output_pdf_charts=False,
        output_merged_pdf=False,
        output_subplot_png=False,
        use_product_catalogs=True,
        ductile_iron_class="PREFERRED",
    ))

    frame = pd.read_csv(result.csv_path)
    row = frame.loc[frame["产品规格ID"] == "DI|GB13295-2026|C40|CML|DN300"].iloc[0]
    assert pd.isna(row["公称壁厚 en (mm)"])
    assert row["产品公称壁厚 (mm)"] == pytest.approx(6.2)
    assert row["水力内径取值依据"] == "DE-2(e_nom+e_c) 名义换算"


def test_product_spec_must_match_material_and_hydraulic_inner_diameter() -> None:
    """通用规格对象不得串管材，也不得用不同于目录的 D 参加计算。"""
    di_spec = get_pipe_product_spec("球墨铸铁管", 300)
    with pytest.raises(ValueError, match="水力计算内径必须与所选产品规格一致"):
        evaluate_single_diameter(
            PressurePipeInput(Q=0.1, material_key="球墨铸铁管"),
            di_spec.inner_diameter_m + 0.001,
            product_spec=di_spec,
        )
    with pytest.raises(ValueError, match="产品规格与当前管材不一致"):
        evaluate_single_diameter(
            PressurePipeInput(Q=0.1, material_key="玻璃钢夹砂管"),
            di_spec.inner_diameter_m,
            product_spec=di_spec,
        )


def test_pccp_structure_variant_is_independent_from_hydraulic_preset() -> None:
    """PCCPE/PCCPL 是产品型式，三档 n 摩阻预设都必须能独立选择同一型式。"""
    for material_key in (
        "预应力钢筒混凝土管",
        "预应力钢筒混凝土管_n014",
        "预应力钢筒混凝土管_n015",
    ):
        result = recommend_diameter(PressurePipeInput(
            Q=0.5,
            material_key=material_key,
            pccp_variant="PCCPE",
            manual_product_diameter_mm=1600,
        ))
        candidate = result.recommended
        assert candidate is not None
        assert candidate.material_key == material_key
        assert candidate.product_family == "PCCP"
        assert candidate.product_variant == "PCCPE"
        assert candidate.nominal_symbol == "DN"
        assert candidate.nominal_diameter_mm == 1600
        assert candidate.D == pytest.approx(1.6)

    with pytest.raises(ValueError, match="不是.*标准公称口径"):
        recommend_diameter(PressurePipeInput(
            Q=0.5,
            material_key="预应力钢筒混凝土管",
            pccp_variant="PCCPL",
            manual_product_diameter_mm=1600,
        ))


def test_frpm_manual_and_automatic_candidates_use_inner_series() -> None:
    """FRPM 指定和自动推荐都只能从表 2 公称内径系列生成水力候选。"""
    manual = recommend_diameter(PressurePipeInput(
        Q=0.5,
        material_key="玻璃钢夹砂管",
        manual_product_diameter_mm=2800,
    ))
    candidate = manual.recommended
    assert candidate is not None
    assert candidate.product_spec_id == "FRPM|ID|DN2800"
    assert candidate.nominal_basis == "公称内径系列"
    assert candidate.hydraulic_inner_diameter_mm == pytest.approx(2800.0)
    assert candidate.D == pytest.approx(2.8)

    automatic = recommend_diameter(PressurePipeInput(Q=0.5, material_key="玻璃钢夹砂管"))
    allowed = set(FRPM_INNER_SERIES_DIAMETERS_MM)
    assert automatic.recommended is not None
    assert automatic.recommended.nominal_diameter_mm in allowed
    assert all(item.product_spec_id.startswith("FRPM|ID|") for item in automatic.top_candidates)
    assert all(item.nominal_diameter_mm in allowed for item in automatic.top_candidates)


def test_legacy_non_pe_inner_diameter_is_rounded_up_without_reinterpretation() -> None:
    """旧项目 D 保持水力内径含义，并安全上取到内径不小于旧值的产品规格。"""
    result = recommend_diameter(PressurePipeInput(
        Q=0.1,
        material_key="球墨铸铁管",
        manual_D=0.3,
        use_product_catalog=True,
    ))

    candidate = result.recommended
    assert result.category == "指定"
    assert candidate is not None
    assert candidate.nominal_diameter_mm == 300
    assert candidate.D == pytest.approx(0.3056)
    assert candidate.D >= 0.3
    assert any("旧版水力内径" in flag and "安全上取" in flag for flag in candidate.flags)
    assert "旧项目规格迁移" in result.reason


def test_explicit_batch_diameter_values_bypass_product_catalog(local_tmp_path) -> None:
    """显式批量 D 序列维持旧接口优先级，不应被产品目录替换。"""
    result = run_batch_scan(BatchScanConfig(
        q_values=np.array([0.1]),
        slope_denominators=[],
        diameter_values=np.array([0.33]),
        materials=["玻璃钢夹砂管"],
        output_dir=str(local_tmp_path),
        output_pdf_charts=False,
        output_merged_pdf=False,
        output_subplot_png=False,
        use_product_catalogs=True,
    ))

    frame = pd.read_csv(result.csv_path)
    assert len(frame) == 1
    assert frame.iloc[0]["D (m)"] == pytest.approx(0.33)
    assert frame.iloc[0]["产品规格ID"] == "" or pd.isna(frame.iloc[0]["产品规格ID"])


def test_frpm_batch_catalog_exports_all_30_inner_series_sizes(local_tmp_path) -> None:
    """未给显式 D 时，FRPM 批量扫描应导出表 2 的全部 30 档内径规格。"""
    result = run_batch_scan(BatchScanConfig(
        q_values=np.array([0.1]),
        slope_denominators=[],
        diameter_values=None,
        materials=["玻璃钢夹砂管"],
        output_dir=str(local_tmp_path),
        output_pdf_charts=False,
        output_merged_pdf=False,
        output_subplot_png=False,
        use_product_catalogs=True,
    ))

    frame = pd.read_csv(result.csv_path)
    assert len(frame) == len(FRPM_INNER_SERIES_DIAMETERS_MM)
    assert set(frame["产品族"]) == {"FRPM"}
    assert tuple(frame["公称口径 (mm)"].astype(int)) == FRPM_INNER_SERIES_DIAMETERS_MM
    assert tuple(frame["水力计算内径 di (mm)"].astype(int)) == FRPM_INNER_SERIES_DIAMETERS_MM
    assert all(value.startswith("FRPM|ID|") for value in frame["产品规格ID"])
