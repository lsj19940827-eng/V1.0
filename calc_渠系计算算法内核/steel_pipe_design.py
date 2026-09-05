# -*- coding: utf-8 -*-
"""按 SL/T 281—2020 构造最小壁厚生成钢管尺寸，供单次和批量水力选径共用。"""

from decimal import Decimal, InvalidOperation, ROUND_CEILING

from calc_渠系计算算法内核.pipe_product_catalog import PipeProductSpec


STEEL_STANDARD = "SL/T 281—2020"
STEEL_SOURCE = "SL/T 281—2020 第8.1.1条（印刷44页／PDF第51页）"
STEEL_DIAMETER_STEP_MM = 100  # 当前设计规范无固定外径系列，按用户指定的整百毫米规则上取
STEEL_MAX_INNER_MM = 10000  # 超过此内径须专项增加最小壁厚，不能仅套本公式
STEEL_DIAMETER_RULE = "SL/T 281—2020未给出固定外径系列，本项目按100 mm整数倍向上取值"
STEEL_SCOPE = (
    "按构造最小壁厚预选，已包括壁厚裕量；内压强度、外压稳定等结构验算另行完成。"
    "外径的100 mm步长为本项目选径规则，不是规范表列产品系列。"
)


def _dimension(value, label, *, allow_zero=False):
    """校验毫米数值，使用十进制避免进位临界点的浮点误差。"""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{label}必须为数值（mm）") from exc
    if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"{label}必须为{'非负' if allow_zero else '大于零的'}有限数值（mm）")
    return number


def get_steel_pipe_spec(diameter_mm, basis="outer", lining_mm=0):
    """固定外径或钢管内径，求满足第8.1.1条的最小整数壁厚并扣除内衬。"""
    diameter = _dimension(diameter_mm, "钢管选径尺寸")
    lining = _dimension(lining_mm, "单侧内衬厚度", allow_zero=True)
    if basis not in {"outer", "inner"}:
        raise ValueError("钢管选径基准必须为外径或钢管内径")
    # 外径固定时 D=De-2t，联立 t≥D/800+4 后求最小整数解；不能先把外径当内径。
    bound = (diameter + 3200) / 802 if basis == "outer" else diameter / 800 + 4
    wall = max(Decimal(6), bound.to_integral_value(rounding=ROUND_CEILING))
    steel_inner = diameter - 2 * wall if basis == "outer" else diameter
    outer = diameter if basis == "outer" else diameter + 2 * wall
    hydraulic_inner = steel_inner - 2 * lining
    if steel_inner > STEEL_MAX_INNER_MM:
        raise ValueError("钢管内径大于10 m时，规范要求适当增加最小壁厚，不能仅按本公式自动预选")
    if hydraulic_inner <= 0:
        raise ValueError("扣除两侧管壁和内衬后的水力内径必须大于零，请检查尺寸")
    label = "公称外径" if basis == "outer" else "钢管内径"
    return PipeProductSpec(
        spec_id=f"STEEL|SLT281-2020|{basis}|D{diameter.normalize()}|t{wall}|lining{lining.normalize()}",
        family="STEEL", material_key="钢管", nominal_symbol="DN" if basis == "outer" else "D",
        nominal_basis=label, nominal_diameter_mm=float(diameter),
        hydraulic_inner_diameter_mm=float(hydraulic_inner),
        hydraulic_inner_diameter_basis="外径减两侧管壁及内衬；构造最小壁厚预选",
        product_standard=STEEL_STANDARD, standard_references=(STEEL_STANDARD,),
        source_locator=STEEL_SOURCE, variant=basis.upper(),
        outer_diameter_mm=float(outer), nominal_wall_thickness_mm=float(wall),
        class_system="壁厚选取", class_code="构造最小壁厚",
        lining_code="用户设置" if lining else "未计内衬", lining_thickness_mm=float(lining),
    )


def get_steel_pipe_specs(diameters_mm, basis="outer", lining_mm=0):
    """逐一验证工程备选尺寸，不静默跳过无效尺寸或替换用户输入。"""
    specs = [get_steel_pipe_spec(value, basis, lining_mm) for value in diameters_mm]
    if not specs:
        raise ValueError("钢管候选尺寸不能为空")
    return tuple(sorted({spec.spec_id: spec for spec in specs}.values(), key=lambda spec: spec.nominal_diameter_mm))


def steel_wall_calculation(candidate):
    """从已保存的尺寸快照生成壁厚公式及代入说明，不重新改变历史计算结果。"""
    outer = candidate.outer_diameter_mm
    wall = candidate.nominal_wall_thickness_mm
    steel_inner = outer - 2 * wall
    common = r"t_{\min}=\max\left(6,\left\lceil D/800+4\right\rceil\right)"
    if candidate.product_variant == "OUTER":
        formula = r"t_{\min}=\max\left(6,\left\lceil(D_e+3200)/802\right\rceil\right)"
        substitution = rf"t_{{\min}}=\max\left(6,\left\lceil({outer:g}+3200)/802\right\rceil\right)={wall:g}\,\mathrm{{mm}}"
        text = f"外径固定，联立 D = De − 2t，t_min = max(6, 向上取整[({outer:g} + 3200) / 802]) = {wall:g} mm"
    else:
        formula = common
        substitution = rf"t_{{\min}}=\max\left(6,\left\lceil{steel_inner:g}/800+4\right\rceil\right)={wall:g}\,\mathrm{{mm}}"
        text = f"内径固定，t_min = max(6, 向上取整[{steel_inner:g} / 800 + 4]) = {wall:g} mm"
    return formula, substitution, text


def steel_dimension_process(candidate):
    """为详细过程和批量结果提供完整、可追溯的尺寸计算文字。"""
    outer, wall, lining = candidate.outer_diameter_mm, candidate.nominal_wall_thickness_mm, candidate.lining_thickness_mm
    return [
        f"依据：{candidate.product_source_locator}",
        "管壁最小厚度 t ≥ D/800 + 4，且不小于6 mm；D为钢管内径，单位均为mm，小数向上进位。",
        steel_wall_calculation(candidate)[2],
        f"钢管内径 D = {outer:g} − 2×{wall:g} = {outer - 2 * wall:g} mm",
        f"水力内径 di = {outer:g} − 2×({wall:g} + {lining:g}) = {candidate.hydraulic_inner_diameter_mm:g} mm",
        STEEL_SCOPE,
    ]
