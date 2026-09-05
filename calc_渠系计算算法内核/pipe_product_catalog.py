# -*- coding: utf-8 -*-
"""有压管道产品规格目录门面，关联球墨铸铁管、PCCP 与 FRPM 规范表列尺寸。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


DI_ENGINEERING_STANDARD = "T/CWHIDA 0002—2018"
DI_PRODUCT_STANDARD = "GB/T 13295—2026"
DI_STANDARD_EFFECTIVE_DATE = "2027-03-01"
DI_LINING_STANDARD = "GB/T 17457—2019"
PCCP_ENGINEERING_STANDARD = "SL 702—2015"
PCCP_PRODUCT_STANDARD = "GB/T 19685—2017"
FRPM_PRODUCT_STANDARD = "GB/T 21238—2016"

PCCP_MATERIAL_KEYS = (
    "预应力钢筒混凝土管",
    "预应力钢筒混凝土管_n014",
    "预应力钢筒混凝土管_n015",
)
CATALOG_FAMILY_BY_MATERIAL = {
    "玻璃钢夹砂管": "FRPM",
    "球墨铸铁管": "DI",
    **{key: "PCCP" for key in PCCP_MATERIAL_KEYS},
}


@dataclass(frozen=True)
class PipeProductSpec:
    """可追溯的管道尺寸快照（表列产品或公式生成的钢管）；无水力内径时禁止计算。"""

    spec_id: str
    family: str
    material_key: str
    nominal_symbol: str
    nominal_basis: str
    nominal_diameter_mm: float
    hydraulic_inner_diameter_mm: Optional[float]
    hydraulic_inner_diameter_basis: str
    product_standard: str
    standard_references: tuple[str, ...]
    source_locator: str
    variant: Optional[str] = None
    outer_diameter_mm: Optional[float] = None
    nominal_wall_thickness_mm: Optional[float] = None
    class_system: Optional[str] = None
    class_code: Optional[str] = None
    lining_code: Optional[str] = None
    lining_thickness_mm: Optional[float] = None
    minimum_inner_diameter_mm: Optional[float] = None
    maximum_inner_diameter_mm: Optional[float] = None
    selected_inner_diameter_tolerance_mm: Optional[float] = None
    reference_only: bool = False

    @property
    def inner_diameter_m(self) -> float:
        """返回水力计算内径，参考规格没有内径时明确阻断。"""
        if self.reference_only or self.hydraulic_inner_diameter_mm is None:
            raise ValueError(f"规格 {self.spec_id} 仅供参考，缺少可用于计算的内径")
        return self.hydraulic_inner_diameter_mm / 1000.0


@dataclass(frozen=True)
class NominalDiameterGuidance:
    """非标准公称口径的上下邻与附近规格。"""

    requested_mm: float
    is_available: bool
    lower_mm: Optional[int]
    upper_mm: Optional[int]
    nearby_mm: tuple[int, ...]


DUCTILE_IRON_NOMINAL_DIAMETERS_MM = (
    40, 50, 60, 65, 80, 100, 125, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700,
    800, 900, 1000, 1100, 1200, 1400, 1500, 1600, 1800, 2000, 2200,
    2400, 2600, 2800, 3000,
)
DUCTILE_IRON_OUTER_DIAMETER_MM = dict(zip(
    DUCTILE_IRON_NOMINAL_DIAMETERS_MM,
    (56, 66, 77, 82, 98, 118, 144, 170, 222, 274, 326, 378, 429, 480, 532, 635, 738,
     842, 945, 1048, 1152, 1255, 1462, 1565, 1668, 1875, 2082, 2288,
     2495, 2702, 2908, 3115),
))

# 用户指定 GB/T 13295—2026 表16、附录C表C.1；空白单元格不补值。
# 新版删除 K 壁厚分级，过渡口径 DN350/C30、DN700/C25 使用表列加厚值。
DUCTILE_IRON_WALL_THICKNESS_MM = {
    "C20": dict(zip(
        DUCTILE_IRON_NOMINAL_DIAMETERS_MM[11:],
        (4.7, 4.8, 5.2, 5.6, 6.4, 7.3, 8.1, 8.9, 9.8, 10.6, 11.4,
         13.1, 13.9, 14.8, 16.4, 18.1, 19.8, 21.4, 23.1, 24.8, 26.4),
    )),
    "C40": dict(zip(
        DUCTILE_IRON_NOMINAL_DIAMETERS_MM[:22],
        (4.4, 4.4, 4.4, 4.4, 4.4, 4.4, 4.5, 4.5, 4.7, 5.5, 6.2, 7.1, 7.8, 8.6, 9.3,
         10.9, 12.4, 14, 15.5, 17.1, 18.7, 20.2),
    )),
    "C30": dict(zip(
        DUCTILE_IRON_NOMINAL_DIAMETERS_MM[9:27],
        (4.6, 5.1, 6.3, 6.5, 6.9, 7.5, 8.7, 9.9, 11.1, 12.3, 13.4, 14.7,
         15.8, 18.2, 19.4, 20.6, 23, 25.4),
    )),
    "C25": dict(zip(
        DUCTILE_IRON_NOMINAL_DIAMETERS_MM[10:],
        (4.6, 5.1, 5.5, 6.1, 6.5, 7.6, 8.8, 9.6, 10.6, 11.6, 12.6, 13.6,
         15.7, 16.7, 17.7, 19.7, 21.8, 23.8, 25.8, 27.9, 29.9, 31.9),
    )),
    "C50": dict(zip(
        DUCTILE_IRON_NOMINAL_DIAMETERS_MM[:21],
        (4.4, 4.4, 4.4, 4.4, 4.4, 4.4, 4.5, 4.5, 5.4, 6.4, 7.4,
         8.4, 9.3, 10.3, 11.2, 13.1, 15.0, 16.9, 18.8, 20.7, 22.7),
    )),
    "C64": dict(zip(
        DUCTILE_IRON_NOMINAL_DIAMETERS_MM[:19],
        (4.4, 4.4, 4.4, 4.4, 4.4, 4.4, 4.8, 5.3, 6.5, 7.8, 8.9,
         10.2, 11.3, 12.6, 13.7, 16.1, 18.5, 21.0, 23.4),
    )),
    "C100": dict(zip(
        DUCTILE_IRON_NOMINAL_DIAMETERS_MM[:17],
        (4.4, 4.4, 4.4, 4.4, 4.8, 5.5, 6.5, 7.4, 9.2, 11.1, 12.9,
         14.8, 16.5, 18.4, 20.2, 23.8, 27.5),
    )),
}
DUCTILE_IRON_CLASS_OPTIONS = ("PREFERRED", "C20", "C25", "C30", "C40", "C50", "C64", "C100")


def _ductile_iron_lining_thickness(dn_mm: int) -> float:
    """按 GB/T 17457—2019 第5.1条、表1返回公称厚度，不采用最小厚度。"""
    if dn_mm <= 300:
        return 4.0
    if dn_mm <= 600:
        return 5.0
    if dn_mm <= 1200:
        return 6.0
    if dn_mm <= 2000:
        return 9.0
    if dn_mm <= 2600:
        return 12.0
    return 15.0


def _preferred_ductile_iron_class(dn_mm: int) -> str:
    """按新版表16首选等级分段返回 C 等级。"""
    if dn_mm <= 300:
        return "C40"
    if dn_mm <= 600:
        return "C30"
    if dn_mm <= 2600:
        return "C25"
    return "C20"


def get_ductile_iron_specs(class_code: str = "PREFERRED") -> tuple[PipeProductSpec, ...]:
    """返回新版所选 C 等级下存在表格单元格的输水球墨铸铁管规格。"""
    normalized = str(class_code or "PREFERRED").strip().upper()
    if normalized in ("K8", "K9", "K10"):
        raise ValueError(
            f"旧等级 {normalized} 不在 {DI_PRODUCT_STANDARD} 目录中（新版已删除 K 壁厚分级）；"
            "请明确选择新版 C 等级后重新计算，原保存结果不自动改写"
        )
    if normalized not in DUCTILE_IRON_CLASS_OPTIONS:
        raise ValueError(f"未知球墨铸铁管壁厚/压力等级 {class_code}；可选 {DUCTILE_IRON_CLASS_OPTIONS}")
    specs = []
    for dn_mm in DUCTILE_IRON_NOMINAL_DIAMETERS_MM:
        actual_class = _preferred_ductile_iron_class(dn_mm) if normalized == "PREFERRED" else normalized
        wall_mm = DUCTILE_IRON_WALL_THICKNESS_MM[actual_class].get(dn_mm)
        if wall_mm is None:
            continue
        de_mm = DUCTILE_IRON_OUTER_DIAMETER_MM[dn_mm]
        lining_mm = _ductile_iron_lining_thickness(dn_mm)
        inner_mm = round(de_mm - 2.0 * (wall_mm + lining_mm), 1)
        specs.append(PipeProductSpec(
            spec_id=f"DI|GB13295-2026|{actual_class}|CML|DN{dn_mm}",
            family="DI", material_key="球墨铸铁管", nominal_symbol="DN",
            nominal_basis="公称尺寸", nominal_diameter_mm=dn_mm,
            hydraulic_inner_diameter_mm=inner_mm,
            hydraulic_inner_diameter_basis="DE-2(e_nom+e_c) 名义换算",
            product_standard=DI_PRODUCT_STANDARD,
            standard_references=(DI_PRODUCT_STANDARD, DI_LINING_STANDARD),
            source_locator=f"{DI_PRODUCT_STANDARD} 4.2.2.2、表16、表C.1；{DI_LINING_STANDARD} 5.1、表1",
            outer_diameter_mm=float(de_mm), nominal_wall_thickness_mm=float(wall_mm),
            class_system=actual_class[0], class_code=actual_class,
            lining_code="CML", lining_thickness_mm=lining_mm,
        ))
    return tuple(specs)


PCCPL_NOMINAL_INNER_DIAMETERS_MM = (400, 500, 600, 700, 800, 900, 1000, 1200, 1400)
PCCPE_NOMINAL_INNER_DIAMETERS_MM = (
    1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800,
    3000, 3200, 3400, 3600, 3800, 4000,
)
PCCP_VARIANTS = ("PCCPE", "PCCPL")


def get_pccp_specs(material_key: str, variant: str = "PCCPE") -> tuple[PipeProductSpec, ...]:
    """按产品结构型式返回 PCCP 基本公称内径；型式与历史摩阻预设相互独立。"""
    if material_key not in PCCP_MATERIAL_KEYS:
        raise ValueError(f"{material_key!r} 不是受支持的 PCCP 管材键；可选 {PCCP_MATERIAL_KEYS}")
    normalized = str(variant or "").strip().upper()
    if normalized not in PCCP_VARIANTS:
        raise ValueError(f"PCCP 产品型式必须为 PCCPE 或 PCCPL，当前为 {variant!r}")
    diameters = (
        PCCPE_NOMINAL_INNER_DIAMETERS_MM
        if normalized == "PCCPE" else PCCPL_NOMINAL_INNER_DIAMETERS_MM
    )
    source_table = "表2、表3" if normalized == "PCCPE" else "表1"
    return tuple(PipeProductSpec(
        spec_id=f"PCCP|{normalized}|D0{diameter}",
        family="PCCP", material_key=material_key, variant=normalized,
        nominal_symbol="DN", nominal_basis="公称内径",
        nominal_diameter_mm=diameter,
        hydraulic_inner_diameter_mm=float(diameter),
        hydraulic_inner_diameter_basis="公称内径",
        product_standard=PCCP_PRODUCT_STANDARD,
        standard_references=(PCCP_ENGINEERING_STANDARD, PCCP_PRODUCT_STANDARD),
        source_locator=f"{PCCP_PRODUCT_STANDARD} {source_table}",
    ) for diameter in diameters)


FRPM_INNER_SERIES_DIAMETERS_MM = (
    100, 125, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700, 800,
    900, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800,
    3000, 3200, 3400, 3600, 3800, 4000,
)
# GB/T 21238—2016 表2：内径系列管两端内直径允许范围。
FRPM_END_INNER_DIAMETER_RANGE_MM = dict(zip(
    FRPM_INNER_SERIES_DIAMETERS_MM,
    (
        (97, 103), (122, 128), (147, 153), (196, 204), (246, 255),
        (296, 306), (346, 357), (396, 408), (446, 459), (496, 510),
        (595, 612), (695, 714), (795, 816), (895, 918), (995, 1020),
        (1195, 1220), (1395, 1420), (1595, 1620), (1795, 1820),
        (1995, 2020), (2195, 2220), (2395, 2420), (2595, 2620),
        (2795, 2820), (2995, 3020), (3195, 3220), (3395, 3420),
        (3595, 3620), (3795, 3820), (3995, 4020),
    ),
))
FRPM_OUTER_SERIES_OUTER_DIAMETER_MM = dict(zip(
    (200, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900, 1000, 1200,
     1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800, 3000, 3200, 3400,
     3600, 3800, 4000),
    (208, 259, 310, 361, 412, 463, 514, 616, 718, 820, 924, 1026, 1229,
     1434, 1638, 1842, 2046, 2250, 2453, 2658, 2861, 3066, 3270, 3474,
     3678, 3882, 4086),
))


def _frpm_selected_inner_diameter_tolerance(dn_mm: int) -> float:
    """返回表2相对所选设计内径值的允许偏差，单位为毫米。"""
    if dn_mm <= 250:
        return 1.5
    if dn_mm == 300:
        return 1.8
    if dn_mm == 350:
        return 2.1
    if dn_mm == 400:
        return 2.4
    if dn_mm == 450:
        return 2.7
    if dn_mm == 500:
        return 3.0
    if dn_mm == 600:
        return 3.6
    if dn_mm <= 1000:
        return 4.2
    if dn_mm <= 2200:
        return 5.0
    if dn_mm <= 3600:
        return 6.0
    return 7.0


def get_frpm_inner_specs() -> tuple[PipeProductSpec, ...]:
    """返回可用于自动水力扫描的 FRPM 公称内径系列。"""
    specs = []
    for diameter in FRPM_INNER_SERIES_DIAMETERS_MM:
        minimum_mm, maximum_mm = FRPM_END_INNER_DIAMETER_RANGE_MM[diameter]
        specs.append(PipeProductSpec(
            spec_id=f"FRPM|ID|DN{diameter}", family="FRPM",
            material_key="玻璃钢夹砂管", nominal_symbol="DN",
            nominal_basis="公称内径系列", nominal_diameter_mm=diameter,
            hydraulic_inner_diameter_mm=float(diameter),
            hydraulic_inner_diameter_basis="内径系列公称直径",
            product_standard=FRPM_PRODUCT_STANDARD,
            standard_references=(FRPM_PRODUCT_STANDARD,),
            source_locator=f"{FRPM_PRODUCT_STANDARD} 6.2.1、表2",
            minimum_inner_diameter_mm=float(minimum_mm),
            maximum_inner_diameter_mm=float(maximum_mm),
            selected_inner_diameter_tolerance_mm=(
                _frpm_selected_inner_diameter_tolerance(diameter)
            ),
        ))
    return tuple(specs)


def get_frpm_outer_reference_specs() -> tuple[PipeProductSpec, ...]:
    """返回 FRPM 外径系列，只作连接和采购参考，不生成水力候选。"""
    return tuple(PipeProductSpec(
        spec_id=f"FRPM|OD|DN{diameter}", family="FRPM",
        material_key="玻璃钢夹砂管", nominal_symbol="DN",
        nominal_basis="公称外径系列（参考）", nominal_diameter_mm=diameter,
        hydraulic_inner_diameter_mm=None,
        hydraulic_inner_diameter_basis="需由供货技术文件给出",
        product_standard=FRPM_PRODUCT_STANDARD,
        standard_references=(FRPM_PRODUCT_STANDARD,),
        source_locator=f"{FRPM_PRODUCT_STANDARD} 6.2.1、表1",
        outer_diameter_mm=float(outer_mm), reference_only=True,
    ) for diameter, outer_mm in FRPM_OUTER_SERIES_OUTER_DIAMETER_MM.items())


def get_catalog_family(material_key: str) -> Optional[str]:
    """返回内部材料键对应的产品目录族。"""
    return CATALOG_FAMILY_BY_MATERIAL.get(material_key)


def get_pipe_product_specs(
    material_key: str,
    *,
    ductile_iron_class: str = "PREFERRED",
    pccp_variant: str = "PCCPE",
) -> tuple[PipeProductSpec, ...]:
    """统一返回指定材料当前选择条件下可用于水力计算的产品规格。"""
    family = get_catalog_family(material_key)
    if family == "DI":
        return get_ductile_iron_specs(ductile_iron_class)
    if family == "PCCP":
        return get_pccp_specs(material_key, pccp_variant)
    if family == "FRPM":
        return get_frpm_inner_specs()
    raise ValueError(f"管材 {material_key!r} 没有本期产品规格目录")


def _normalize_requested_mm(value: object) -> float:
    """把用户公称口径规范化为正有限数，拒绝布尔值和小数规格。"""
    if isinstance(value, bool):
        raise ValueError("公称口径必须是标准表列的正整数毫米值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("公称口径必须是标准表列的正整数毫米值") from exc
    if not math.isfinite(number) or number <= 0 or not number.is_integer():
        raise ValueError("公称口径必须是标准表列的正整数毫米值")
    return number


def get_nominal_diameter_guidance(
    material_key: str,
    requested_mm: object,
    *,
    ductile_iron_class: str = "PREFERRED",
    pccp_variant: str = "PCCPE",
) -> NominalDiameterGuidance:
    """查询当前产品目录中的合法性、上下邻及附近四档规格。"""
    requested = _normalize_requested_mm(requested_mm)
    diameters = tuple(spec.nominal_diameter_mm for spec in get_pipe_product_specs(
        material_key,
        ductile_iron_class=ductile_iron_class,
        pccp_variant=pccp_variant,
    ))
    lower = max((diameter for diameter in diameters if diameter < requested), default=None)
    upper = min((diameter for diameter in diameters if diameter > requested), default=None)
    ranked = sorted(diameters, key=lambda diameter: (abs(diameter - requested), diameter))[:4]
    nearby = tuple(sorted(ranked))
    return NominalDiameterGuidance(
        requested_mm=requested,
        is_available=int(requested) in diameters,
        lower_mm=lower,
        upper_mm=upper,
        nearby_mm=nearby,
    )


def get_pipe_product_spec(
    material_key: str,
    nominal_diameter_mm: object,
    *,
    ductile_iron_class: str = "PREFERRED",
    pccp_variant: str = "PCCPE",
) -> PipeProductSpec:
    """精确取得一个合法表列规格，非标准值给出可执行的邻近建议。"""
    guidance = get_nominal_diameter_guidance(
        material_key, nominal_diameter_mm,
        ductile_iron_class=ductile_iron_class, pccp_variant=pccp_variant,
    )
    specs = get_pipe_product_specs(
        material_key,
        ductile_iron_class=ductile_iron_class, pccp_variant=pccp_variant,
    )
    if guidance.is_available:
        return next(spec for spec in specs if spec.nominal_diameter_mm == int(guidance.requested_mm))
    nearby = "、".join(str(value) for value in guidance.nearby_mm)
    bounds = []
    if guidance.lower_mm is not None:
        bounds.append(f"相邻下一级 {guidance.lower_mm} mm")
    if guidance.upper_mm is not None:
        bounds.append(f"相邻上一级 {guidance.upper_mm} mm")
    suggestion = (
        f"建议先从上邻规格 {guidance.upper_mm} mm 重新校核"
        if guidance.upper_mm is not None
        else "当前目录没有更大的上邻规格，请调整产品型式或管材"
    )
    raise ValueError(
        f"{guidance.requested_mm:g} mm 不是当前选择条件下的标准公称口径；"
        f"附近规范规格（mm）：{nearby}；{'，'.join(bounds)}；{suggestion}"
    )


def format_pipe_product_spec(spec: PipeProductSpec, include_standards: bool = True) -> str:
    """生成界面、日志和计算书共用的产品规格摘要。"""
    if spec.family == "DI":
        text = (
            f"球墨铸铁管 DN{spec.nominal_diameter_mm}，{spec.class_code}，"
            f"DE{spec.outer_diameter_mm:g}×e{spec.nominal_wall_thickness_mm:g} mm，"
            f"水泥砂浆内衬 {spec.lining_thickness_mm:g} mm，"
            f"名义换算 di={spec.hydraulic_inner_diameter_mm:g} mm"
        )
    elif spec.family == "PCCP":
        variant_name = "埋置式" if spec.variant == "PCCPE" else "内衬式"
        text = f"{variant_name}预应力钢筒混凝土管 {spec.variant}，DN={spec.nominal_diameter_mm} mm"
    elif spec.family == "FRPM" and spec.reference_only:
        text = (
            f"玻璃钢夹砂管，外径系列 DN{spec.nominal_diameter_mm}，"
            f"实际外径 {spec.outer_diameter_mm:g} mm，仅供参考，"
            "水力内径需由供货技术文件给出"
        )
    elif spec.family == "FRPM":
        text = (
            f"玻璃钢夹砂管，内径系列 DN{spec.nominal_diameter_mm}，"
            f"两端内径允许范围 {spec.minimum_inner_diameter_mm:g}～"
            f"{spec.maximum_inner_diameter_mm:g} mm"
        )
    else:
        text = f"{spec.family}，{spec.nominal_symbol}{spec.nominal_diameter_mm}"
    if include_standards:
        text += "，" + "、".join(spec.standard_references)
    return text
