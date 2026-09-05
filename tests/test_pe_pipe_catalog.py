# -*- coding: utf-8 -*-
"""PE 实壁给水管规范目录的逐表数据和查询接口测试。"""

from dataclasses import FrozenInstanceError
import os
import sys

import pytest


# 直接加载算法内核目录，保持与既有内核测试相同的导入方式。
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "calc_渠系计算算法内核"))

from pe_pipe_catalog import (  # noqa: E402
    PE_NOMINAL_OUTER_DIAMETERS_MM,
    PE_PN_SDR_BY_GRADE,
    PE_STANDARD,
    PE_WALL_THICKNESS_MM_BY_SDR,
    PENominalDiameterGuidance,
    PEPipeSpec,
    get_pe_nominal_diameter_guidance,
    get_pe_pipe_spec,
    get_pe_pipe_specs,
    get_pe_pressure_options,
    get_pe_sdr,
)


EXPECTED_DIAMETERS = (
    16,
    20,
    25,
    32,
    40,
    50,
    63,
    75,
    90,
    110,
    125,
    140,
    160,
    180,
    200,
    225,
    250,
    280,
    315,
    355,
    400,
    450,
    500,
    560,
    630,
    710,
    800,
    900,
    1000,
    1200,
    1400,
    1600,
    1800,
    2000,
    2250,
    2500,
)

EXPECTED_DIAMETERS_BY_SDR = {
    9.0: EXPECTED_DIAMETERS[0:27],
    11.0: EXPECTED_DIAMETERS[1:29],
    13.6: EXPECTED_DIAMETERS[2:32],
    17.0: EXPECTED_DIAMETERS[3:34],
    21.0: EXPECTED_DIAMETERS[4:36],
    26.0: EXPECTED_DIAMETERS[5:36],
    33.0: EXPECTED_DIAMETERS[18:36],
    41.0: EXPECTED_DIAMETERS[18:36],
}


def test_standard_and_all_36_nominal_outer_diameters() -> None:
    """表 2 的标准号和 36 个公称外径应完整且有序。"""
    assert PE_STANDARD == "GB/T 13663.2—2018"
    assert PE_NOMINAL_OUTER_DIAMETERS_MM == EXPECTED_DIAMETERS
    assert len(PE_NOMINAL_OUTER_DIAMETERS_MM) == 36


def test_all_pressure_to_sdr_mappings() -> None:
    """PE80、PE100 的全部 PN/SDR 对应关系应与表 3 表头一致。"""
    assert dict(PE_PN_SDR_BY_GRADE["PE80"]) == {
        1.6: 9.0,
        1.25: 11.0,
        1.0: 13.6,
        0.8: 17.0,
        0.6: 21.0,
        0.5: 26.0,
        0.4: 33.0,
        0.32: 41.0,
    }
    assert dict(PE_PN_SDR_BY_GRADE["PE100"]) == {
        2.0: 9.0,
        1.6: 11.0,
        1.25: 13.6,
        1.0: 17.0,
        0.8: 21.0,
        0.6: 26.0,
        0.5: 33.0,
        0.4: 41.0,
    }
    assert get_pe_pressure_options("PE80") == (1.6, 1.25, 1.0, 0.8, 0.6, 0.5, 0.4, 0.32)
    assert get_pe_pressure_options("pe 100") == (2.0, 1.6, 1.25, 1.0, 0.8, 0.6, 0.5, 0.4)


@pytest.mark.parametrize(
    ("grade", "pn_mpa", "expected_sdr"),
    [
        ("PE80", 1.6, 9.0),
        ("PE80", 0.32, 41.0),
        ("PE100", 2.0, 9.0),
        ("PE100", 1.0, 17.0),
        ("PE100", 0.4, 41.0),
    ],
)
def test_get_pe_sdr(grade: str, pn_mpa: float, expected_sdr: float) -> None:
    """SDR 查询应覆盖两个材料等级的高、中、低压力边界。"""
    assert get_pe_sdr(grade, pn_mpa) == expected_sdr


def test_wall_thickness_matrix_has_exact_allowed_diameters() -> None:
    """每列壁厚的公称外径集合应严格匹配表 3 的有效单元格。"""
    assert set(PE_WALL_THICKNESS_MM_BY_SDR) == set(EXPECTED_DIAMETERS_BY_SDR)
    for sdr, expected_diameters in EXPECTED_DIAMETERS_BY_SDR.items():
        assert tuple(PE_WALL_THICKNESS_MM_BY_SDR[sdr]) == expected_diameters
    assert sum(len(values) for values in PE_WALL_THICKNESS_MM_BY_SDR.values()) == 215


def test_sdr17_examples_for_dn315_and_dn355() -> None:
    """对话中的 SDR17 示例应得到规范壁厚和对应名义水力内径。"""
    dn315 = get_pe_pipe_spec("PE100", 1.0, 315)
    dn355 = get_pe_pipe_spec("PE100", 1.0, 355)

    assert isinstance(dn315, PEPipeSpec)
    assert dn315.grade == "PE100"
    assert dn315.nominal_outer_diameter_mm == 315
    assert dn315.sdr == 17.0
    assert dn315.pn_mpa == 1.0
    assert dn315.nominal_wall_thickness_mm == 18.7
    assert dn315.hydraulic_inner_diameter_mm == 277.6
    assert dn315.inner_diameter_m == pytest.approx(0.2776)
    assert dn315.standard == PE_STANDARD

    assert dn355.nominal_wall_thickness_mm == 21.1
    assert dn355.hydraulic_inner_diameter_mm == 312.8
    assert dn355.inner_diameter_m == pytest.approx(0.3128)


def test_visually_verified_special_wall_thickness_cells_are_preserved() -> None:
    """表 3 影像核对的三个特殊原值应保留，不能用 DN/SDR 公式覆盖。"""
    assert PE_WALL_THICKNESS_MM_BY_SDR[11.0][1000] == 90.2
    assert PE_WALL_THICKNESS_MM_BY_SDR[13.6][1000] == 72.5
    assert PE_WALL_THICKNESS_MM_BY_SDR[17.0][1200] == 67.9

    assert get_pe_pipe_spec("PE100", 1.6, 1000).hydraulic_inner_diameter_mm == 819.6
    assert get_pe_pipe_spec("PE100", 1.25, 1000).hydraulic_inner_diameter_mm == 855.0
    assert get_pe_pipe_spec("PE100", 1.0, 1200).hydraulic_inner_diameter_mm == 1064.2


@pytest.mark.parametrize(
    ("grade", "pn_mpa", "expected_sdr", "first_dn", "last_dn", "count"),
    [
        ("PE100", 2.0, 9.0, 16, 800, 27),
        ("PE100", 1.6, 11.0, 20, 1000, 28),
        ("PE100", 1.25, 13.6, 25, 1600, 30),
        ("PE100", 1.0, 17.0, 32, 2000, 31),
        ("PE100", 0.8, 21.0, 40, 2500, 32),
        ("PE100", 0.6, 26.0, 50, 2500, 31),
        ("PE100", 0.5, 33.0, 315, 2500, 18),
        ("PE100", 0.4, 41.0, 315, 2500, 18),
    ],
)
def test_get_pe_pipe_specs_obeys_table_ranges(
    grade: str,
    pn_mpa: float,
    expected_sdr: float,
    first_dn: int,
    last_dn: int,
    count: int,
) -> None:
    """规格列表应按表 3 的离散范围过滤并保持公称外径升序。"""
    specs = get_pe_pipe_specs(grade, pn_mpa)
    assert len(specs) == count
    assert specs[0].nominal_outer_diameter_mm == first_dn
    assert specs[-1].nominal_outer_diameter_mm == last_dn
    assert all(spec.sdr == expected_sdr for spec in specs)
    assert [spec.nominal_outer_diameter_mm for spec in specs] == sorted(
        spec.nominal_outer_diameter_mm for spec in specs
    )


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("PE40",), "材料等级"),
        ((100,), "材料等级"),
    ],
)
def test_invalid_grade_is_rejected(args: tuple[object, ...], message: str) -> None:
    """未知或非字符串材料等级应给出明确错误。"""
    with pytest.raises(ValueError, match=message):
        get_pe_pressure_options(*args)


@pytest.mark.parametrize(
    ("grade", "pn_mpa"),
    [
        ("PE100", 0.32),
        ("PE80", 2.0),
        ("PE100", True),
        ("PE100", "abc"),
    ],
)
def test_invalid_pressure_is_rejected(grade: str, pn_mpa: object) -> None:
    """材料等级不支持或格式无效的压力值应被拒绝。"""
    with pytest.raises(ValueError, match="压力|支持"):
        get_pe_sdr(grade, pn_mpa)


@pytest.mark.parametrize("dn_mm", [300, 315.5, True, "abc"])
def test_nonstandard_diameter_is_rejected(dn_mm: object) -> None:
    """非表 2 公称外径或无效格式应被拒绝。"""
    with pytest.raises(ValueError, match="公称外径"):
        get_pe_pipe_spec("PE100", 1.0, dn_mm)


def test_nonstandard_dn600_returns_nearby_valid_diameters() -> None:
    """输入 600 mm 时应给出两侧相邻值和附近四个当前组合有效规格。"""
    guidance = get_pe_nominal_diameter_guidance("PE100", 1.0, 600)

    assert isinstance(guidance, PENominalDiameterGuidance)
    assert guidance.requested_mm == 600
    assert guidance.is_available is False
    assert guidance.lower_mm == 560
    assert guidance.upper_mm == 630
    assert guidance.nearby_mm == (500, 560, 630, 710)

    with pytest.raises(ValueError) as exc_info:
        get_pe_pipe_spec("PE100", 1.0, 600)
    message = str(exc_info.value)
    assert "附近规范 DN（mm）：500、560、630、710" in message
    assert "相邻下一级 560 mm" in message
    assert "相邻上一级 630 mm" in message
    assert "建议先从上邻规格 DN=630 mm" in message


def test_available_and_out_of_range_diameter_guidance() -> None:
    """合法规格及超出当前组合上限时应返回无歧义的规格位置。"""
    valid = get_pe_nominal_diameter_guidance("PE100", 1.0, 630)
    assert valid.is_available is True
    assert valid.lower_mm == 560
    assert valid.upper_mm == 710

    oversized = get_pe_nominal_diameter_guidance("PE100", 1.0, 2500)
    assert oversized.is_available is False
    assert oversized.lower_mm == 2000
    assert oversized.upper_mm is None
    assert oversized.nearby_mm == (1400, 1600, 1800, 2000)


@pytest.mark.parametrize(
    ("grade", "pn_mpa", "dn_mm"),
    [
        ("PE100", 2.0, 900),
        ("PE100", 1.6, 16),
        ("PE100", 1.25, 1800),
        ("PE100", 1.0, 2250),
        ("PE80", 0.4, 280),
    ],
)
def test_standard_diameter_in_illegal_sdr_combination_is_rejected(
    grade: str, pn_mpa: float, dn_mm: int
) -> None:
    """虽属表 2 但未列入相应 SDR 列的公称外径应被拒绝。"""
    with pytest.raises(ValueError, match="不包含公称外径"):
        get_pe_pipe_spec(grade, pn_mpa, dn_mm)


def test_pipe_spec_is_frozen() -> None:
    """返回的规范规格应不可变，避免运行期污染目录数据。"""
    spec = get_pe_pipe_spec("PE100", 1.0, 315)
    with pytest.raises(FrozenInstanceError):
        spec.nominal_wall_thickness_mm = 20.0
