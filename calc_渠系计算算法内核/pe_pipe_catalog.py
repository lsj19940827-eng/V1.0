# -*- coding: utf-8 -*-
"""PE 实壁给水管规范目录，供有压管道水力计算与后续选型界面共用。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping


PE_STANDARD = "GB/T 13663.2—2018"

PE_NOMINAL_OUTER_DIAMETERS_MM = (
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

PE_PN_SDR_BY_GRADE: Mapping[str, Mapping[float, float]] = MappingProxyType(
    {
        "PE80": MappingProxyType(
            {
                1.6: 9.0,
                1.25: 11.0,
                1.0: 13.6,
                0.8: 17.0,
                0.6: 21.0,
                0.5: 26.0,
                0.4: 33.0,
                0.32: 41.0,
            }
        ),
        "PE100": MappingProxyType(
            {
                2.0: 9.0,
                1.6: 11.0,
                1.25: 13.6,
                1.0: 17.0,
                0.8: 21.0,
                0.6: 26.0,
                0.5: 33.0,
                0.4: 41.0,
            }
        ),
    }
)

# 壁厚逐格抄录并经表 3 影像核对；不能用 dn/SDR 反算替代，包括与理论商值不同的表列值。
PE_WALL_THICKNESS_MM_BY_SDR: Mapping[float, Mapping[int, float]] = MappingProxyType(
    {
        9.0: MappingProxyType(
            {
                16: 2.3,
                20: 2.3,
                25: 3.0,
                32: 3.6,
                40: 4.5,
                50: 5.6,
                63: 7.1,
                75: 8.4,
                90: 10.1,
                110: 12.3,
                125: 14.0,
                140: 15.7,
                160: 17.9,
                180: 20.1,
                200: 22.4,
                225: 25.2,
                250: 27.9,
                280: 31.3,
                315: 35.2,
                355: 39.7,
                400: 44.7,
                450: 50.3,
                500: 55.8,
                560: 62.5,
                630: 70.3,
                710: 79.3,
                800: 89.3,
            }
        ),
        11.0: MappingProxyType(
            {
                20: 2.3,
                25: 2.3,
                32: 3.0,
                40: 3.7,
                50: 4.6,
                63: 5.8,
                75: 6.8,
                90: 8.2,
                110: 10.0,
                125: 11.4,
                140: 12.7,
                160: 14.6,
                180: 16.4,
                200: 18.2,
                225: 20.5,
                250: 22.7,
                280: 25.4,
                315: 28.6,
                355: 32.2,
                400: 36.3,
                450: 40.9,
                500: 45.4,
                560: 50.8,
                630: 57.2,
                710: 64.5,
                800: 72.6,
                900: 81.7,
                1000: 90.2,
            }
        ),
        13.6: MappingProxyType(
            {
                25: 2.3,
                32: 2.4,
                40: 3.0,
                50: 3.7,
                63: 4.7,
                75: 5.6,
                90: 6.7,
                110: 8.1,
                125: 9.2,
                140: 10.3,
                160: 11.8,
                180: 13.3,
                200: 14.7,
                225: 16.6,
                250: 18.4,
                280: 20.6,
                315: 23.2,
                355: 26.1,
                400: 29.4,
                450: 33.1,
                500: 36.8,
                560: 41.2,
                630: 46.3,
                710: 52.2,
                800: 58.8,
                900: 66.2,
                1000: 72.5,
                1200: 88.2,
                1400: 102.9,
                1600: 117.6,
            }
        ),
        17.0: MappingProxyType(
            {
                32: 2.3,
                40: 2.4,
                50: 3.0,
                63: 3.8,
                75: 4.5,
                90: 5.4,
                110: 6.6,
                125: 7.4,
                140: 8.3,
                160: 9.5,
                180: 10.7,
                200: 11.9,
                225: 13.4,
                250: 14.8,
                280: 16.6,
                315: 18.7,
                355: 21.1,
                400: 23.7,
                450: 26.7,
                500: 29.7,
                560: 33.2,
                630: 37.4,
                710: 42.1,
                800: 47.4,
                900: 53.3,
                1000: 59.3,
                1200: 67.9,
                1400: 82.4,
                1600: 94.1,
                1800: 105.9,
                2000: 117.6,
            }
        ),
        21.0: MappingProxyType(
            {
                40: 2.3,
                50: 2.4,
                63: 3.0,
                75: 3.6,
                90: 4.3,
                110: 5.3,
                125: 6.0,
                140: 6.7,
                160: 7.7,
                180: 8.6,
                200: 9.6,
                225: 10.8,
                250: 11.9,
                280: 13.4,
                315: 15.0,
                355: 16.9,
                400: 19.1,
                450: 21.5,
                500: 23.9,
                560: 26.7,
                630: 30.0,
                710: 33.9,
                800: 38.1,
                900: 42.9,
                1000: 47.7,
                1200: 57.2,
                1400: 66.7,
                1600: 76.2,
                1800: 85.7,
                2000: 95.2,
                2250: 107.2,
                2500: 119.1,
            }
        ),
        26.0: MappingProxyType(
            {
                50: 2.3,
                63: 2.5,
                75: 2.9,
                90: 3.5,
                110: 4.2,
                125: 4.8,
                140: 5.4,
                160: 6.2,
                180: 6.9,
                200: 7.7,
                225: 8.6,
                250: 9.6,
                280: 10.7,
                315: 12.1,
                355: 13.6,
                400: 15.3,
                450: 17.2,
                500: 19.1,
                560: 21.4,
                630: 24.1,
                710: 27.2,
                800: 30.6,
                900: 34.4,
                1000: 38.2,
                1200: 45.9,
                1400: 53.5,
                1600: 61.2,
                1800: 69.1,
                2000: 76.9,
                2250: 86.0,
                2500: 95.6,
            }
        ),
        33.0: MappingProxyType(
            {
                315: 9.7,
                355: 10.9,
                400: 12.3,
                450: 13.8,
                500: 15.3,
                560: 17.2,
                630: 19.3,
                710: 21.8,
                800: 24.5,
                900: 27.6,
                1000: 30.6,
                1200: 36.7,
                1400: 42.9,
                1600: 49.0,
                1800: 54.5,
                2000: 60.6,
                2250: 70.0,
                2500: 77.7,
            }
        ),
        41.0: MappingProxyType(
            {
                315: 7.7,
                355: 8.7,
                400: 9.8,
                450: 11.0,
                500: 12.3,
                560: 13.7,
                630: 15.4,
                710: 17.4,
                800: 19.6,
                900: 22.0,
                1000: 24.5,
                1200: 29.4,
                1400: 34.3,
                1600: 39.2,
                1800: 43.8,
                2000: 48.8,
                2250: 55.0,
                2500: 61.2,
            }
        ),
    }
)


@dataclass(frozen=True)
class PEPipeSpec:
    """表示一个由材料等级、压力等级和标准尺寸共同确定的 PE 管规格。"""

    grade: str
    nominal_outer_diameter_mm: int
    sdr: float
    pn_mpa: float
    nominal_wall_thickness_mm: float
    hydraulic_inner_diameter_mm: float
    standard: str

    @property
    def inner_diameter_m(self) -> float:
        """将名义水力内径由毫米换算为米。"""
        return self.hydraulic_inner_diameter_mm / 1000.0


@dataclass(frozen=True)
class PENominalDiameterGuidance:
    """描述一个输入外径在当前 PE 规格系列中的位置和附近可选值。"""

    requested_mm: float
    is_available: bool
    lower_mm: int | None
    upper_mm: int | None
    nearby_mm: tuple[int, ...]


def _normalize_grade(grade: str) -> str:
    """将常见的 PE 材料等级写法规范为 PE80 或 PE100。"""
    if not isinstance(grade, str):
        raise ValueError("PE 材料等级必须是字符串，例如 PE80 或 PE100")
    normalized = grade.upper().replace(" ", "").replace("-", "").replace("_", "")
    if normalized not in PE_PN_SDR_BY_GRADE:
        raise ValueError(f"不支持的 PE 材料等级：{grade!r}；可选 PE80、PE100")
    return normalized


def _normalize_pressure(grade: str, pn_mpa: float) -> tuple[str, float]:
    """校验压力等级，并返回规范化材料等级和标准 PN 数值。"""
    normalized_grade = _normalize_grade(grade)
    if isinstance(pn_mpa, bool):
        raise ValueError("PE 管公称压力必须是数值，单位为 MPa")
    try:
        normalized_pn = float(pn_mpa)
    except (TypeError, ValueError) as exc:
        raise ValueError("PE 管公称压力必须是数值，单位为 MPa") from exc
    if normalized_pn not in PE_PN_SDR_BY_GRADE[normalized_grade]:
        options = ", ".join(str(value) for value in get_pe_pressure_options(normalized_grade))
        raise ValueError(
            f"{normalized_grade} 不支持 PN {normalized_pn:g} MPa；可选值：{options} MPa"
        )
    return normalized_grade, normalized_pn


def _normalize_nominal_outer_diameter(dn_mm: float) -> int:
    """校验并规范化 PE 管公称外径。"""
    if isinstance(dn_mm, bool):
        raise ValueError("PE 管公称外径必须是数值，单位为 mm")
    try:
        numeric_dn = float(dn_mm)
    except (TypeError, ValueError) as exc:
        raise ValueError("PE 管公称外径必须是数值，单位为 mm") from exc
    if not numeric_dn.is_integer():
        raise ValueError(f"PE 管公称外径必须取标准整数规格，当前为 {numeric_dn:g} mm")
    normalized_dn = int(numeric_dn)
    if normalized_dn not in PE_NOMINAL_OUTER_DIAMETERS_MM:
        raise ValueError(f"{normalized_dn} mm 不是 {PE_STANDARD} 表 2 的标准公称外径")
    return normalized_dn


def _build_spec(grade: str, pn_mpa: float, sdr: float, dn_mm: int, wall_mm: float) -> PEPipeSpec:
    """由一个合法表 3 单元格构造不可变 PE 管规格。"""
    return PEPipeSpec(
        grade=grade,
        nominal_outer_diameter_mm=dn_mm,
        sdr=sdr,
        pn_mpa=pn_mpa,
        nominal_wall_thickness_mm=wall_mm,
        hydraulic_inner_diameter_mm=round(dn_mm - 2.0 * wall_mm, 1),
        standard=PE_STANDARD,
    )


def get_pe_pressure_options(grade: str) -> tuple[float, ...]:
    """按标准表列顺序返回指定 PE 材料等级的公称压力选项。"""
    normalized_grade = _normalize_grade(grade)
    return tuple(PE_PN_SDR_BY_GRADE[normalized_grade])


def get_pe_sdr(grade: str, pn_mpa: float) -> float:
    """返回指定 PE 材料等级和公称压力对应的标准尺寸比。"""
    normalized_grade, normalized_pn = _normalize_pressure(grade, pn_mpa)
    return PE_PN_SDR_BY_GRADE[normalized_grade][normalized_pn]


def get_pe_pipe_specs(grade: str, pn_mpa: float) -> tuple[PEPipeSpec, ...]:
    """按公称外径升序返回指定材料和压力下的全部合法 PE 管规格。"""
    normalized_grade, normalized_pn = _normalize_pressure(grade, pn_mpa)
    sdr = PE_PN_SDR_BY_GRADE[normalized_grade][normalized_pn]
    wall_thicknesses = PE_WALL_THICKNESS_MM_BY_SDR[sdr]
    return tuple(
        _build_spec(normalized_grade, normalized_pn, sdr, dn_mm, wall_thicknesses[dn_mm])
        for dn_mm in PE_NOMINAL_OUTER_DIAMETERS_MM
        if dn_mm in wall_thicknesses
    )


def get_pe_nominal_diameter_guidance(
    grade: str,
    pn_mpa: float,
    dn_mm: float,
) -> PENominalDiameterGuidance:
    """返回输入外径附近最多四个当前等级和压力下可用的规范规格。"""
    if isinstance(dn_mm, bool):
        raise ValueError("PE 管公称外径必须是数值，单位为 mm")
    try:
        numeric_dn = float(dn_mm)
    except (TypeError, ValueError) as exc:
        raise ValueError("PE 管公称外径必须是数值，单位为 mm") from exc
    if not math.isfinite(numeric_dn) or numeric_dn <= 0:
        raise ValueError("PE 管公称外径必须是大于 0 的有限数值，单位为 mm")

    available_dns = tuple(
        spec.nominal_outer_diameter_mm for spec in get_pe_pipe_specs(grade, pn_mpa)
    )
    is_available = numeric_dn.is_integer() and int(numeric_dn) in available_dns
    lower_mm = max((dn for dn in available_dns if dn < numeric_dn), default=None)
    upper_mm = min((dn for dn in available_dns if dn > numeric_dn), default=None)
    nearby_mm = tuple(sorted(
        sorted(available_dns, key=lambda dn: (abs(dn - numeric_dn), dn))[:4]
    ))
    return PENominalDiameterGuidance(
        requested_mm=numeric_dn,
        is_available=is_available,
        lower_mm=lower_mm,
        upper_mm=upper_mm,
        nearby_mm=nearby_mm,
    )


def _format_nearby_diameter_guidance(guidance: PENominalDiameterGuidance) -> str:
    """把附近规范规格整理成适合错误提示的简短文本。"""
    nearby_text = "、".join(str(dn) for dn in guidance.nearby_mm)
    bounds = []
    if guidance.lower_mm is not None:
        bounds.append(f"相邻下一级 {guidance.lower_mm} mm")
    if guidance.upper_mm is not None:
        bounds.append(f"相邻上一级 {guidance.upper_mm} mm")
    text = f"附近规范 DN（mm）：{nearby_text}"
    if bounds:
        text += f"；{'，'.join(bounds)}"
    if guidance.upper_mm is not None:
        text += (
            f"。为避免直接减小过流断面，建议先从上邻规格 DN={guidance.upper_mm} mm "
            "开始重新进行水力校核"
        )
    else:
        text += "。当前组合没有更大的上邻规格，请调整材料等级、PN 或另行论证"
    return text


def get_pe_pipe_spec(grade: str, pn_mpa: float, dn_mm: float) -> PEPipeSpec:
    """返回一个指定材料、压力和公称外径的合法 PE 管规格。"""
    normalized_grade, normalized_pn = _normalize_pressure(grade, pn_mpa)
    sdr = PE_PN_SDR_BY_GRADE[normalized_grade][normalized_pn]
    wall_thicknesses = PE_WALL_THICKNESS_MM_BY_SDR[sdr]
    available_dns = tuple(
        dn for dn in PE_NOMINAL_OUTER_DIAMETERS_MM if dn in wall_thicknesses
    )
    available_text = "、".join(str(dn) for dn in available_dns)
    try:
        guidance = get_pe_nominal_diameter_guidance(
            normalized_grade, normalized_pn, dn_mm
        )
    except ValueError:
        guidance = None
    try:
        normalized_dn = _normalize_nominal_outer_diameter(dn_mm)
    except ValueError as exc:
        options_text = (
            f"可选 DN 的{_format_nearby_diameter_guidance(guidance)}"
            if guidance is not None
            else f"可选 DN（mm）：{available_text}"
        )
        raise ValueError(
            f"{exc}；{normalized_grade}、PN {normalized_pn:g} MPa（SDR {sdr:g}）"
            f"的离散规格中，{options_text}"
        ) from exc
    if normalized_dn not in wall_thicknesses:
        guidance_text = _format_nearby_diameter_guidance(guidance)
        raise ValueError(
            f"{normalized_grade}、PN {normalized_pn:g} MPa（SDR {sdr:g}）"
            f"不包含公称外径 {normalized_dn} mm；{guidance_text}"
        )
    return _build_spec(
        normalized_grade,
        normalized_pn,
        sdr,
        normalized_dn,
        wall_thicknesses[normalized_dn],
    )


__all__ = [
    "PE_STANDARD",
    "PE_NOMINAL_OUTER_DIAMETERS_MM",
    "PE_PN_SDR_BY_GRADE",
    "PE_WALL_THICKNESS_MM_BY_SDR",
    "PEPipeSpec",
    "PENominalDiameterGuidance",
    "get_pe_pressure_options",
    "get_pe_sdr",
    "get_pe_pipe_specs",
    "get_pe_nominal_diameter_guidance",
    "get_pe_pipe_spec",
]
