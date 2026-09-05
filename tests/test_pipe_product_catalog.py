# -*- coding: utf-8 -*-
"""球墨铸铁管、PCCP 与 FRPM 产品规格目录的逐表数据和查询接口测试。"""

from dataclasses import FrozenInstanceError

import pytest

from calc_渠系计算算法内核.pipe_product_catalog import (
    DI_ENGINEERING_STANDARD,
    DI_LINING_STANDARD,
    DI_STANDARD_EFFECTIVE_DATE,
    DUCTILE_IRON_CLASS_OPTIONS,
    DI_PRODUCT_STANDARD,
    DUCTILE_IRON_NOMINAL_DIAMETERS_MM,
    DUCTILE_IRON_OUTER_DIAMETER_MM,
    DUCTILE_IRON_WALL_THICKNESS_MM,
    FRPM_END_INNER_DIAMETER_RANGE_MM,
    FRPM_INNER_SERIES_DIAMETERS_MM,
    FRPM_OUTER_SERIES_OUTER_DIAMETER_MM,
    FRPM_PRODUCT_STANDARD,
    PCCPE_NOMINAL_INNER_DIAMETERS_MM,
    PCCPL_NOMINAL_INNER_DIAMETERS_MM,
    PCCP_ENGINEERING_STANDARD,
    PCCP_MATERIAL_KEYS,
    PCCP_PRODUCT_STANDARD,
    format_pipe_product_spec,
    get_ductile_iron_specs,
    get_frpm_inner_specs,
    get_frpm_outer_reference_specs,
    get_nominal_diameter_guidance,
    get_pccp_specs,
    get_pipe_product_spec,
    get_pipe_product_specs,
)


EXPECTED_DI_DIAMETERS = (
    40, 50, 60, 65, 80, 100, 125, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700,
    800, 900, 1000, 1100, 1200, 1400, 1500, 1600, 1800, 2000, 2200,
    2400, 2600, 2800, 3000,
)
EXPECTED_DI_OUTER_DIAMETERS = (
    56, 66, 77, 82, 98, 118, 144, 170, 222, 274, 326, 378, 429, 480, 532, 635, 738,
    842, 945, 1048, 1152, 1255, 1462, 1565, 1668, 1875, 2082, 2288,
    2495, 2702, 2908, 3115,
)
EXPECTED_PCCPL_DIAMETERS = (400, 500, 600, 700, 800, 900, 1000, 1200, 1400)
EXPECTED_PCCPE_DIAMETERS = (
    1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800,
    3000, 3200, 3400, 3600, 3800, 4000,
)
EXPECTED_FRPM_INNER_DIAMETERS = (
    100, 125, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700, 800,
    900, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800,
    3000, 3200, 3400, 3600, 3800, 4000,
)
EXPECTED_FRPM_OUTER_SERIES = (
    200, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900, 1000, 1200,
    1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800, 3000, 3200, 3400,
    3600, 3800, 4000,
)
EXPECTED_FRPM_ACTUAL_OUTER_DIAMETERS = (
    208, 259, 310, 361, 412, 463, 514, 616, 718, 820, 924, 1026, 1229,
    1434, 1638, 1842, 2046, 2250, 2453, 2658, 2861, 3066, 3270, 3474,
    3678, 3882, 4086,
)


def test_standard_identifiers_are_kept_with_catalog_data() -> None:
    """工程标准和产品标准应保持分层，不能只留下产品表或混成一条依据。"""
    assert DI_ENGINEERING_STANDARD == "T/CWHIDA 0002—2018"
    assert DI_PRODUCT_STANDARD == "GB/T 13295—2026"
    assert DI_LINING_STANDARD == "GB/T 17457—2019"
    assert DI_STANDARD_EFFECTIVE_DATE == "2027-03-01"
    assert PCCP_ENGINEERING_STANDARD == "SL 702—2015"
    assert PCCP_PRODUCT_STANDARD == "GB/T 19685—2017"
    assert FRPM_PRODUCT_STANDARD == "GB/T 21238—2016"


def test_ductile_iron_2026_series_has_exactly_32_sizes() -> None:
    """按用户指定新版表16完整开放 DN40～DN3000 的32档。"""
    assert DUCTILE_IRON_NOMINAL_DIAMETERS_MM == EXPECTED_DI_DIAMETERS
    assert tuple(DUCTILE_IRON_OUTER_DIAMETER_MM) == EXPECTED_DI_DIAMETERS
    assert tuple(DUCTILE_IRON_OUTER_DIAMETER_MM.values()) == EXPECTED_DI_OUTER_DIAMETERS
    assert len(get_ductile_iron_specs("PREFERRED")) == 32


def test_ductile_iron_wall_matrix_preserves_blank_cells() -> None:
    """新版表C.1空白单元格不得外推，旧 K 类必须明确拒绝。"""
    expected_keys = {
        "C20": EXPECTED_DI_DIAMETERS[11:],
        "C25": EXPECTED_DI_DIAMETERS[10:],
        "C30": EXPECTED_DI_DIAMETERS[9:27],
        "C40": EXPECTED_DI_DIAMETERS[:22],
        "C50": EXPECTED_DI_DIAMETERS[:21],
        "C64": EXPECTED_DI_DIAMETERS[:19],
        "C100": EXPECTED_DI_DIAMETERS[:17],
    }
    for class_code, diameters in expected_keys.items():
        assert tuple(DUCTILE_IRON_WALL_THICKNESS_MM[class_code]) == diameters
        assert len(get_ductile_iron_specs(class_code)) == len(diameters)

    assert set(DUCTILE_IRON_CLASS_OPTIONS) == {"PREFERRED", *expected_keys}
    assert sum(map(len, DUCTILE_IRON_WALL_THICKNESS_MM.values())) == 140
    assert 1400 not in DUCTILE_IRON_WALL_THICKNESS_MM["C40"]
    for old_class in ("K8", "K9", "K10"):
        with pytest.raises(ValueError, match="新版已删除 K"):
            get_ductile_iron_specs(old_class)


@pytest.mark.parametrize(
    ("dn_mm", "expected_class", "expected_de", "expected_wall", "expected_lining"),
    [
        (40, "C40", 56.0, 4.4, 4.0),
        (65, "C40", 82.0, 4.4, 4.0),
        (80, "C40", 98.0, 4.4, 4.0),
        (300, "C40", 326.0, 6.2, 4.0),
        (350, "C30", 378.0, 6.3, 5.0),
        (600, "C30", 635.0, 8.7, 5.0),
        (700, "C25", 738.0, 8.8, 6.0),
        (1200, "C25", 1255.0, 13.6, 6.0),
        (1400, "C25", 1462.0, 15.7, 9.0),
        (2000, "C25", 2082.0, 21.8, 9.0),
        (2200, "C25", 2288.0, 23.8, 12.0),
        (2600, "C25", 2702.0, 27.9, 12.0),
        (2800, "C20", 2908.0, 24.8, 15.0),
        (3000, "C20", 3115.0, 26.4, 15.0),
    ],
)
def test_preferred_di_class_and_hydraulic_inner_diameter_formula(
    dn_mm: int,
    expected_class: str,
    expected_de: float,
    expected_wall: float,
    expected_lining: float,
) -> None:
    """首选压力级遵守新版表16，内衬采用配套2019版公称值。"""
    spec = get_pipe_product_spec("球墨铸铁管", dn_mm)
    expected_inner = expected_de - 2.0 * (expected_wall + expected_lining)

    assert spec.class_code == expected_class
    assert spec.outer_diameter_mm == expected_de
    assert spec.nominal_wall_thickness_mm == expected_wall
    assert spec.lining_thickness_mm == expected_lining
    assert spec.hydraulic_inner_diameter_mm == pytest.approx(expected_inner)
    assert spec.inner_diameter_m == pytest.approx(expected_inner / 1000.0)
    assert spec.standard_references == (DI_PRODUCT_STANDARD, DI_LINING_STANDARD)
    assert "GB13295-2026" in spec.spec_id


def test_explicit_di_class_uses_only_cells_existing_in_that_column() -> None:
    """显式 C 级别必须使用自身列，不能偷偷切换到首选等级。"""
    c30_dn300 = get_pipe_product_spec("球墨铸铁管", 300, ductile_iron_class="C30")
    assert c30_dn300.class_code == "C30"
    assert c30_dn300.nominal_wall_thickness_mm == 5.1

    with pytest.raises(ValueError, match="不是.*标准公称口径"):
        get_pipe_product_spec("球墨铸铁管", 200, ductile_iron_class="C30")
    with pytest.raises(ValueError, match="新版已删除 K"):
        get_pipe_product_spec("球墨铸铁管", 2200, ductile_iron_class="K8")


@pytest.mark.parametrize("class_code,dn,wall", [
    ("C20", 350, 4.7), ("C20", 1600, 14.8), ("C25", 300, 4.6),
    ("C25", 3000, 31.9), ("C30", 250, 4.6), ("C30", 400, 6.5),
    ("C50", 1100, 22.7), ("C64", 250, 7.8), ("C64", 900, 23.4),
    ("C100", 500, 20.2), ("C100", 700, 27.5),
])
def test_2026_new_and_ocr_sensitive_wall_cells(class_code, dn, wall):
    """锁定新增列、过渡壁厚及OCR容易错列的原表单元格。"""
    assert get_pipe_product_spec("球墨铸铁管", dn, ductile_iron_class=class_code).nominal_wall_thickness_mm == wall


def test_pccpl_and_pccpe_keep_distinct_basic_inner_diameter_series() -> None:
    """PCCPL 与 PCCPE 应按产品标准表列型式分开，默认采用 PCCPE。"""
    assert PCCPL_NOMINAL_INNER_DIAMETERS_MM == EXPECTED_PCCPL_DIAMETERS
    assert PCCPE_NOMINAL_INNER_DIAMETERS_MM == EXPECTED_PCCPE_DIAMETERS

    for material_key in PCCP_MATERIAL_KEYS:
        default_specs = get_pipe_product_specs(material_key)
        pccpl_specs = get_pipe_product_specs(material_key, pccp_variant="PCCPL")
        assert tuple(spec.nominal_diameter_mm for spec in default_specs) == EXPECTED_PCCPE_DIAMETERS
        assert tuple(spec.nominal_diameter_mm for spec in pccpl_specs) == EXPECTED_PCCPL_DIAMETERS
        assert all(spec.material_key == material_key for spec in default_specs + pccpl_specs)
        assert all(spec.inner_diameter_m == spec.nominal_diameter_mm / 1000 for spec in default_specs + pccpl_specs)
        assert all(
            spec.standard_references == (PCCP_ENGINEERING_STANDARD, PCCP_PRODUCT_STANDARD)
            for spec in default_specs + pccpl_specs
        )

    with pytest.raises(ValueError, match="PCCPE 或 PCCPL"):
        get_pccp_specs(PCCP_MATERIAL_KEYS[0], "PCCPA")
    with pytest.raises(ValueError, match="PCCP 管材键"):
        get_pccp_specs("钢管", "PCCPE")


def test_frpm_inner_series_is_hydraulic_and_outer_series_is_reference_only() -> None:
    """FRPM 仅内径系列进入水力扫描，外径系列没有壁厚时不得反算内径。"""
    assert FRPM_INNER_SERIES_DIAMETERS_MM == EXPECTED_FRPM_INNER_DIAMETERS
    assert tuple(FRPM_OUTER_SERIES_OUTER_DIAMETER_MM) == EXPECTED_FRPM_OUTER_SERIES
    assert tuple(FRPM_OUTER_SERIES_OUTER_DIAMETER_MM.values()) == EXPECTED_FRPM_ACTUAL_OUTER_DIAMETERS

    hydraulic_specs = get_pipe_product_specs("玻璃钢夹砂管")
    reference_specs = get_frpm_outer_reference_specs()
    assert tuple(spec.nominal_diameter_mm for spec in hydraulic_specs) == EXPECTED_FRPM_INNER_DIAMETERS
    assert len(reference_specs) == 27
    assert all(not spec.reference_only for spec in hydraulic_specs)
    assert all(spec.reference_only for spec in reference_specs)
    assert all(spec.hydraulic_inner_diameter_mm is None for spec in reference_specs)
    assert all(spec.spec_id.startswith("FRPM|ID|") for spec in hydraulic_specs)
    assert all(spec.spec_id.startswith("FRPM|OD|") for spec in reference_specs)
    assert FRPM_END_INNER_DIAMETER_RANGE_MM[100] == (97, 103)
    assert FRPM_END_INNER_DIAMETER_RANGE_MM[1000] == (995, 1020)
    assert FRPM_END_INNER_DIAMETER_RANGE_MM[2800] == (2795, 2820)
    assert FRPM_END_INNER_DIAMETER_RANGE_MM[4000] == (3995, 4020)
    by_dn = {spec.nominal_diameter_mm: spec for spec in hydraulic_specs}
    assert by_dn[100].selected_inner_diameter_tolerance_mm == 1.5
    assert by_dn[600].selected_inner_diameter_tolerance_mm == 3.6
    assert by_dn[1000].selected_inner_diameter_tolerance_mm == 4.2
    assert by_dn[2200].selected_inner_diameter_tolerance_mm == 5.0
    assert by_dn[3600].selected_inner_diameter_tolerance_mm == 6.0
    assert by_dn[4000].selected_inner_diameter_tolerance_mm == 7.0

    with pytest.raises(ValueError, match="仅供参考.*缺少.*内径"):
        _ = reference_specs[0].inner_diameter_m
    assert "外径系列" in format_pipe_product_spec(reference_specs[0])
    assert "仅供参考" in format_pipe_product_spec(reference_specs[0])


def test_generic_guidance_returns_exact_neighbors_and_four_nearby_sizes() -> None:
    """非标输入应同时返回上下邻和按距离选出的四个附近表列规格。"""
    guidance = get_nominal_diameter_guidance("球墨铸铁管", 130)
    assert guidance.requested_mm == 130
    assert guidance.is_available is False
    assert guidance.lower_mm == 125
    assert guidance.upper_mm == 150
    assert guidance.nearby_mm == (80, 100, 125, 150)

    valid = get_nominal_diameter_guidance("玻璃钢夹砂管", 2800)
    assert valid.is_available is True
    assert valid.lower_mm == 2600
    assert valid.upper_mm == 3000

    below_pccpe = get_nominal_diameter_guidance(
        PCCP_MATERIAL_KEYS[0], 900, pccp_variant="PCCPE"
    )
    assert below_pccpe.lower_mm is None
    assert below_pccpe.upper_mm == 1000
    assert below_pccpe.nearby_mm == (1000, 1200, 1400, 1600)

    with pytest.raises(ValueError) as exc_info:
        get_pipe_product_spec("球墨铸铁管", 130)
    message = str(exc_info.value)
    assert "附近规范规格（mm）：80、100、125、150" in message
    assert "相邻下一级 125 mm" in message
    assert "相邻上一级 150 mm" in message
    assert "建议先从上邻规格 150 mm" in message


@pytest.mark.parametrize("value", [0, -100, 100.5, True, float("nan"), float("inf"), "abc"])
def test_generic_guidance_rejects_invalid_nominal_diameter(value: object) -> None:
    """公称口径查询只接受正有限整数毫米值。"""
    with pytest.raises(ValueError, match="正整数毫米值"):
        get_nominal_diameter_guidance("球墨铸铁管", value)


def test_catalog_specs_are_frozen() -> None:
    """目录对象应不可变，避免一次计算污染后续工况。"""
    spec = get_frpm_inner_specs()[0]
    with pytest.raises(FrozenInstanceError):
        spec.nominal_diameter_mm = 200
