# -*- coding: utf-8 -*-
"""
有压管道设计计算内核

提供：管材参数、口径序列、加大流量、单管径评价、推荐算法、批量扫描、详细过程文本。
所有函数均为纯函数，无全局副作用，供面板和测试调用。
"""

import math
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Callable

import numpy as np
import pandas as pd
from calc_渠系计算算法内核.unpressurized_comparison import (
    STANDARD_SLOPES, DEFAULT_CLEARANCE_HEIGHT, DEFAULT_CLEARANCE_AREA,
    normal_flow, compare_flows, COMPARISON_COLUMNS,
)

from calc_渠系计算算法内核.pe_pipe_catalog import (
    PEPipeSpec,
    get_pe_pipe_spec,
    get_pe_pipe_specs,
)
from calc_渠系计算算法内核.pipe_product_catalog import (
    PipeProductSpec,
    get_catalog_family,
    get_pipe_product_spec,
    get_pipe_product_specs,
)
from calc_渠系计算算法内核.steel_pipe_design import (
    get_steel_pipe_spec, get_steel_pipe_specs, steel_dimension_process,
    STEEL_DIAMETER_STEP_MM, STEEL_MAX_INNER_MM,
)
from calc_渠系计算算法内核.steel_hydraulic_sizing import (
    recommend_steel_pipe, steel_hydraulic_requirement, select_steel_outer_diameter, steel_sizing_process,
)

# ============================================================
# 1. 常量与配置
# ============================================================

DUCTILE_IRON_F_LOWER = 1.899e5
DUCTILE_IRON_F_UPPER = 2.232e5
# 用数学公式绘制立方米上角标，避免 SimHei 缺少 Unicode ³ 字形。
PLOT_FLOW_UNIT_M3_PER_S = r"m$^3$/s"


PIPE_MATERIALS = {
    "HDPE管":           {
        "f": 0.948e5,
        "m": 1.77,
        "b": 4.77,
        # name 作为批量 CSV 等既有外部接口的稳定值；display_name 仅供新界面展示。
        "name": "HDPE管",
        "display_name": "聚乙烯（PE）管",
        "uses_pe_catalog": True,
    },
    "玻璃钢夹砂管":     {
        "f": 0.948e5,
        "m": 1.77,
        "b": 4.77,
        "name": "玻璃钢夹砂管",
        "catalog_family": "FRPM",
    },
    "球墨铸铁管":       {
        "f": DUCTILE_IRON_F_UPPER,
        "f_min": DUCTILE_IRON_F_LOWER,
        "f_max": DUCTILE_IRON_F_UPPER,
        "m": 1.852,
        "b": 4.87,
        "name": "球墨铸铁管",
        "catalog_family": "DI",
    },
    "预应力钢筒混凝土管": {
        "f": 1.312e6,
        "m": 2.0,
        "b": 5.33,
        "name": "预应力钢筒混凝土管(n=0.013)",
        "catalog_family": "PCCP",
        "hydraulic_preset": "n=0.013",
    },
    "预应力钢筒混凝土管_n014": {
        "f": 1.516e6,
        "m": 2.0,
        "b": 5.33,
        "name": "预应力钢筒混凝土管(n=0.014)",
        "catalog_family": "PCCP",
        "hydraulic_preset": "n=0.014",
    },
    "预应力钢筒混凝土管_n015": {
        "f": 1.749e6,
        "m": 2.0,
        "b": 5.33,
        "name": "预应力钢筒混凝土管(n=0.015)",
        "catalog_family": "PCCP",
        "hydraulic_preset": "n=0.015",
    },
    "钢管":             {"f": 6.25e5,  "m": 1.9,  "b": 5.1,  "name": "钢管"},
}

# ---- GB 50288-2018 §6.7.2 规范条文 ----
SPEC_672_TEXT = """
《灌溉与排水工程设计标准》 GB 50288—2018  第6.7.2条

6.7.2  灌溉输水管道设计应符合下列规定：

  1  管道设计流量应根据控制的灌溉面积计算确定。

  2  管道沿程水头损失和局部水头损失，可按下列公式计算：

     沿程水头损失公式 (6.7.2-1)：
         hf = f × L×Q^m / d^b

     局部水头损失公式 (6.7.2-2)：
         hj = ζ × V² / (2g)

     式中：
       hf —— 管道沿程水头损失 (m)
       f  —— 摩阻系数，按表6.7.2取值
       L  —— 管道长度 (m)
       Q  —— 流量 (m³/h)
       m  —— 流量指数，按表6.7.2取值
       d  —— 管道内径 (mm)
       b  —— 管径指数，按表6.7.2取值
       hj —— 管道局部水头损失 (m)
       ζ  —— 管道局部阻力系数
       V  —— 管道流速 (m/s)
       g  —— 重力加速度 (m/s²)

  3  管道设计流速宜控制在经济流速 0.9m/s～1.5m/s，
     超出此范围时应经技术经济比较确定。

表6.7.2  各种管材的 f、m、b 值：
  ┌──────────────────────────┬──────────────┬───────┬───────┐
  │ 管    材                 │      f       │   m   │   b   │
  ├──────────────────────────┼──────────────┼───────┼───────┤
  │ 钢筋混凝土管 (n=0.013)  │ 1.312×10⁶   │  2.00 │  5.33 │
  │ 钢筋混凝土管 (n=0.014)  │ 1.516×10⁶   │  2.00 │  5.33 │
  │ 钢管、铸铁管             │ 6.25×10⁵    │  1.90 │  5.10 │
  │ 硬聚氯乙烯塑料管(PVC-U) │ 0.948×10⁵   │  1.77 │  4.77 │
  │ 铝合金管                 │ 0.861×10⁵   │  1.74 │  4.74 │
  │ 聚乙烯管(PE)             │ 0.948×10⁵   │  1.77 │  4.77 │
  │ 玻璃钢管(RPMP)           │ 0.948×10⁵   │  1.77 │  4.77 │
  └──────────────────────────┴──────────────┴───────┴───────┘
""".strip()

# V9 口径序列 (m)
_D_small  = np.round(np.arange(0.1, 0.55, 0.05), 2)
_D_medium = np.round(np.arange(0.6, 1.6, 0.1), 1)
_D_large  = np.round(np.arange(1.6, 3.2, 0.2), 1)
DEFAULT_DIAMETER_SERIES = np.concatenate([_D_small, _D_medium, _D_large])

# 批量扫描默认参数
DEFAULT_Q_RANGE = np.round(np.arange(0.1, 2.1, 0.1), 1)
DEFAULT_SLOPE_DENOMINATORS = list(STANDARD_SLOPES)
DEFAULT_SLOPE_RANGE = [1.0 / d for d in DEFAULT_SLOPE_DENOMINATORS]

# 推荐规则阈值
ECONOMIC_RULE = {"v_min": 0.9, "v_max": 1.5, "hf_max": 5.0}
COMPROMISE_RULE = {"v_min": 0.6, "v_max": 0.9, "hf_max": 5.0}


# ============================================================
# 2. 数据结构
# ============================================================

@dataclass
class PressurePipeInput:
    """单次计算输入"""
    Q: float                       # 设计流量 (m3/s)
    material_key: str              # 管材键名
    slope_i: Optional[float] = None   # 无压部分坡度 (如 1/2000 = 0.0005), None 则跳过无压计算
    n_unpr: float = 0.014          # 无压部分糙率
    length_m: float = 1000.0       # 管长 (m)
    manual_increase_percent: Optional[float] = None  # 手动加大比例 (%), None 则自动
    local_loss_ratio: float = 0.15  # 局部损失占沿程损失的比例, 默认 0.15
    manual_D: Optional[float] = None  # 用户指定管径 (m), None 则自动推荐
    pe_material_grade: str = "PE100"  # PE 材料等级，仅 HDPE管 使用
    pe_nominal_pressure_mpa: float = 1.0  # 20℃、C=1.25 时的 PE 公称压力
    manual_nominal_diameter_mm: Optional[float] = None  # PE 指定公称外径 dn (mm)
    use_product_catalog: bool = True  # 非 PE 目录管材是否按规范表列规格选径
    manual_product_diameter_mm: Optional[float] = None  # 非 PE 指定产品公称口径 (mm)
    ductile_iron_class: str = "PREFERRED"  # 球墨铸铁管新版 C 等级或按口径分段的首选压力级
    pccp_variant: str = "PCCPE"  # PCCP 型式；与历史摩阻参数预设独立
    steel_dimensions_enabled: bool = False  # 旧接口保留水力内径；新界面显式启用钢管尺寸
    steel_dimension_basis: str = "outer"  # 新计算仅固定外径；历史内径由界面换算后传入
    steel_lining_thickness_mm: float = 0.0  # 单侧内衬；不属于钢板壁厚
    manual_steel_diameter_mm: Optional[float] = None  # 指定钢管公称外径（mm），不强制整百
    steel_diameter_candidates_mm: Optional[tuple[float, ...]] = None  # 旧字段保留供读取，新单次选径拒绝自定义序列


@dataclass
class DiameterCandidate:
    """单管径评价结果"""
    D: float               # 管径 (m)
    V_press: float         # 有压流速 (m/s)
    hf_friction_km: float  # 沿程水头损失 (m/km)
    hf_local_km: float     # 局部水头损失 (m/km)
    hf_total_km: float     # 总水头损失 (m/km)
    h_loss_total_m: float  # 按管长折算总损失 (m)
    increase_pct: float    # 加大流量百分比 (%)
    Q_increased: float     # 加大后流量 (m3/s)
    # 球墨铸铁管 f 下限对比结果；其他管材保持 None
    hf_friction_lower_km: Optional[float] = None
    hf_local_lower_km: Optional[float] = None
    hf_total_lower_km: Optional[float] = None
    h_loss_total_lower_m: Optional[float] = None
    # 无压计算结果
    y_unpr: float = float('nan')          # 无压水深 (m)
    v_unpr: float = float('nan')          # 无压流速 (m/s)
    y_D_ratio: float = float('nan')       # 充满度 y/D
    Q_full_unpr: float = float('nan')     # 满管流量 (m3/s)
    Q_max_unpr: float = float('nan')      # 最大无压流量 (m3/s)
    clearance_h: float = float('nan')     # 净空高度 (m)
    clearance_a_pct: float = float('nan') # 净空面积百分比 (%)
    flag_clr_h: bool = False              # 净空高度<0.4m 标记
    flag_clr_a: bool = False              # 净空面积<15% 标记
    unpr_notes: str = ""                  # 无压计算备注
    category: str = ""     # "经济" / "妥协" / "兜底"
    flags: List[str] = field(default_factory=list)
    # PE 规格元数据；D 始终保留为水力计算内径（m），便于兼容既有调用。
    hydraulic_inner_diameter_mm: Optional[float] = None
    nominal_outer_diameter_mm: Optional[int] = None
    nominal_wall_thickness_mm: Optional[float] = None
    pe_material_grade: Optional[str] = None
    pe_sdr: Optional[float] = None
    pe_nominal_pressure_mpa: Optional[float] = None
    product_standard: Optional[str] = None
    # 通用产品规格元数据；旧字段继续保留，确保 PE 与历史项目兼容。
    material_key: Optional[str] = None
    product_spec_id: Optional[str] = None
    product_family: Optional[str] = None
    product_variant: Optional[str] = None
    nominal_symbol: Optional[str] = None
    nominal_basis: Optional[str] = None
    hydraulic_inner_diameter_basis: Optional[str] = None
    nominal_diameter_mm: Optional[float] = None
    outer_diameter_mm: Optional[float] = None
    class_system: Optional[str] = None
    class_code: Optional[str] = None
    lining_code: Optional[str] = None
    lining_thickness_mm: Optional[float] = None
    minimum_inner_diameter_mm: Optional[float] = None
    maximum_inner_diameter_mm: Optional[float] = None
    selected_inner_diameter_tolerance_mm: Optional[float] = None
    product_standard_references: tuple[str, ...] = field(default_factory=tuple)
    product_source_locator: Optional[str] = None
    steel_sizing_trace: Optional[dict] = None  # 保存水力下限、补壁厚和外径上取全过程


@dataclass
class RecommendationResult:
    """推荐结果"""
    recommended: Optional[DiameterCandidate]
    top_candidates: List[DiameterCandidate]
    category: str          # "经济" / "妥协" / "兜底" / "指定" / "无可用"
    reason: str
    calc_steps: str        # 完整计算过程文本
    auto_recommended: Optional[DiameterCandidate] = None  # 自动推荐结果（仅指定D时有值）


@dataclass
class BatchScanConfig:
    """批量扫描配置"""
    q_values: np.ndarray
    slope_denominators: List[int]
    diameter_values: Optional[np.ndarray]
    materials: List[str]           # 管材键名列表
    n_unpr: float = 0.014
    length_m: float = 1000.0
    local_loss_ratio: float = 0.15  # 局部损失比例
    output_dir: str = ""
    # ===== 输出选项 (可按需开启/关闭) =====
    output_csv: bool = True           # CSV计算结果：包含所有工况的原始数据，便于后续分析
    output_pdf_charts: bool = True    # 无压能力/充满度/流速对比图与有压优选点图
    output_merged_pdf: bool = True    # 合并PDF：将所有图表合并成一个完整文档
    output_subplot_png: bool = True   # 子图PNG：每个Q值生成独立的高清PNG图片(300DPI)
    pe_material_grade: str = "PE100"  # PE 批量扫描材料等级
    pe_nominal_pressure_mpa: float = 1.0  # PE 批量扫描公称压力 (MPa)
    use_product_catalogs: bool = True  # 非 PE 目录管材是否扫描规范离散规格
    ductile_iron_class: str = "PREFERRED"  # 球墨铸铁管等级选择
    pccp_variant: str = "PCCPE"  # PCCP 产品型式
    steel_dimensions_enabled: bool = False  # 保持旧批量脚本接口兼容
    steel_dimension_basis: str = "outer"
    steel_lining_thickness_mm: float = 0.0
    steel_diameter_candidates_mm: Optional[tuple[float, ...]] = None
    unpr_clearance_height: Optional[float] = None  # 项目自定净空高度下限
    unpr_clearance_area: Optional[float] = None  # 项目自定净空面积百分比下限


@dataclass
class BatchScanResult:
    """批量扫描结果"""
    csv_path: str = ""
    generated_pngs: List[str] = field(default_factory=list)
    generated_pdfs: List[str] = field(default_factory=list)
    merged_pdf: str = ""
    logs: List[str] = field(default_factory=list)
    comparison_rows: List[dict] = field(default_factory=list)
    comparison_csv_path: str = ""


# ============================================================
# 3. 计算函数
# ============================================================

def get_flow_increase_percent(Q: float) -> float:
    """根据设计流量返回加大百分比 (%)"""
    if Q <= 0:
        return 0.0
    elif Q < 1:
        return 30.0
    elif Q < 5:
        return 25.0
    elif Q < 20:
        return 20.0
    elif Q < 50:
        return 15.0
    elif Q < 100:
        return 10.0
    else:
        return 5.0


def _calc_q_max_unpressurized(D: float, n: float, i: float) -> float:
    """计算圆管无压最大流量 (y/D ≈ 0.938 时取得)"""
    if D <= 0 or n <= 0 or i <= 0:
        return 0.0
    theta_opt = 5.278  # 对应 y/D=0.938
    k_A = (1.0 / 8.0) * (theta_opt - math.sin(theta_opt))
    k_R = (1.0 / 4.0) * (1.0 - math.sin(theta_opt) / theta_opt)
    A_opt = k_A * D ** 2
    R_opt = max(0.0, k_R * D)
    return (1.0 / n) * A_opt * (R_opt ** (2.0 / 3.0)) * (i ** 0.5)


def solve_unpressurized(Q: float, D: float, n: float, i: float):
    """兼容既有元组接口；以括区间求根消除初值依赖，旧净空标记仅作兼容字段。"""
    r = normal_flow(Q, D, n, i)
    number = lambda key: float('nan') if r[key] is None else r[key]
    return (number('depth'), number('velocity'), number('filling'), r['full_capacity'], r['capacity'],
            number('clearance_height'), number('clearance_area'),
            r['depth'] is not None and r['clearance_height'] < DEFAULT_CLEARANCE_HEIGHT,
            r['depth'] is not None and r['clearance_area'] < DEFAULT_CLEARANCE_AREA,
            f"Q>{r['capacity']:.4f}(Q_max_unpr)" if r['status'] == '能力不足' else r['reason'])


def _validate_hydraulic_number(value: float, label: str, *, allow_zero: bool = False) -> None:
    """拒绝非有限水力输入，避免无效数值进入规格推荐和成果导出。"""
    requirement = "大于等于 0" if allow_zero else "大于 0"
    try:
        valid = (
            not isinstance(value, (bool, np.bool_)) and math.isfinite(value)
            and (value >= 0 if allow_zero else value > 0)
        )
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise ValueError(f"{label} 必须{requirement}，且为有限数值，当前为 {value!r}")


def _validate_pressure_pipe_input(inp: PressurePipeInput) -> None:
    """统一校验单次与候选评价共用的水力参数。"""
    _validate_hydraulic_number(inp.Q, "设计流量 Q")
    _validate_hydraulic_number(inp.length_m, "管长 L")
    _validate_hydraulic_number(inp.local_loss_ratio, "局部损失比例", allow_zero=True)
    if inp.manual_increase_percent is not None:
        _validate_hydraulic_number(inp.manual_increase_percent, "加大流量百分比", allow_zero=True)
    if inp.slope_i is not None:
        _validate_hydraulic_number(inp.slope_i, "无压坡度")
        _validate_hydraulic_number(inp.n_unpr, "无压糙率 n")
    if inp.manual_D is not None:
        _validate_hydraulic_number(inp.manual_D, "指定水力内径 D")
    if inp.material_key == '钢管' and inp.steel_dimensions_enabled:
        _validate_hydraulic_number(inp.steel_lining_thickness_mm, '单侧内衬厚度', allow_zero=True)


def evaluate_single_diameter(
    inp: PressurePipeInput,
    D: float,
    *,
    pe_spec: Optional[PEPipeSpec] = None,
    product_spec: Optional[PipeProductSpec] = None,
) -> DiameterCandidate:
    """
    对给定水力计算内径 D 评价有压管道水力性能。

    PE 管由 ``pe_spec`` 携带既有规格；DI、PCCP、FRPM 由 ``product_spec``
    携带通用产品规格。D 必须等于规格的名义水力内径；无规格对象的旧调用继续有效。

    公式:
        V_press = Q / A_full
        Q_inc = Q * (1 + p/100)
        hf_friction_km = f * (1000 * Q_inc_m3h^m) / (d_mm^b)
        hf_local_km = local_loss_ratio * hf_friction_km
        hf_total_km = hf_friction_km + hf_local_km
        h_total_m = hf_total_km * (L / 1000)
    """
    _validate_hydraulic_number(D, "管径 D")
    _validate_pressure_pipe_input(inp)
    if inp.material_key not in PIPE_MATERIALS:
        raise ValueError(f"未知管材: {inp.material_key}")

    mat = PIPE_MATERIALS[inp.material_key]
    if pe_spec is not None and product_spec is not None:
        raise ValueError("PE 规格与通用产品规格不能同时传入")
    if pe_spec is not None:
        if not mat.get("uses_pe_catalog"):
            raise ValueError("PE 产品规格只能用于聚乙烯（PE）管")
        if not math.isclose(D, pe_spec.inner_diameter_m, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("PE 水力计算内径必须与所选 DN、en 规格一致")
    if product_spec is not None:
        expected_family = "STEEL" if inp.material_key == "钢管" else get_catalog_family(inp.material_key)
        if expected_family != product_spec.family or product_spec.material_key != inp.material_key:
            raise ValueError("产品规格与当前管材不一致")
        if not math.isclose(D, product_spec.inner_diameter_m, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("水力计算内径必须与所选产品规格一致")
    f_c, m_c, b_c = mat["f"], mat["m"], mat["b"]

    A_full = math.pi * D ** 2 / 4.0
    V_press = inp.Q / A_full

    # 加大流量
    if inp.manual_increase_percent is not None:
        pct = max(0.0, inp.manual_increase_percent)
    else:
        pct = get_flow_increase_percent(inp.Q)

    Q_inc = inp.Q * (1.0 + pct / 100.0)
    Q_inc_m3h = Q_inc * 3600.0
    d_mm = D * 1000.0

    # 沿程水头损失 (m/km)
    hf_friction_km = f_c * (1000.0 * (Q_inc_m3h ** m_c)) / (d_mm ** b_c)
    hf_local_km = inp.local_loss_ratio * hf_friction_km
    hf_total_km = hf_friction_km + hf_local_km
    h_loss_total_m = hf_total_km * (inp.length_m / 1000.0)

    # 球墨铸铁管的 f 为规范区间，同时给出同一管径下限结果供用户选用。
    hf_friction_lower_km = None
    hf_local_lower_km = None
    hf_total_lower_km = None
    h_loss_total_lower_m = None
    f_lower = mat.get("f_min")
    if f_lower is not None and float(f_lower) < float(f_c):
        hf_friction_lower_km = (
            float(f_lower) * (1000.0 * (Q_inc_m3h ** m_c)) / (d_mm ** b_c)
        )
        hf_local_lower_km = inp.local_loss_ratio * hf_friction_lower_km
        hf_total_lower_km = hf_friction_lower_km + hf_local_lower_km
        h_loss_total_lower_m = hf_total_lower_km * (inp.length_m / 1000.0)

    # 分类
    flags = []
    if ECONOMIC_RULE["v_min"] <= V_press <= ECONOMIC_RULE["v_max"] and hf_total_km <= ECONOMIC_RULE["hf_max"]:
        category = "经济"
    elif COMPROMISE_RULE["v_min"] <= V_press < COMPROMISE_RULE["v_max"] and hf_total_km <= COMPROMISE_RULE["hf_max"]:
        category = "妥协"
    else:
        category = "兜底"
        if V_press < COMPROMISE_RULE["v_min"]:
            flags.append("流速过低")
        if V_press > ECONOMIC_RULE["v_max"]:
            flags.append("流速过高")
        if hf_total_km > ECONOMIC_RULE["hf_max"]:
            flags.append("水损过大")

    # 无压计算 (仅当提供了 slope_i 时)
    y_u = v_u = yD_u = Qf_u = Qm_u = ch_u = ca_u = float('nan')
    fch = fca = False
    notes_u = ""
    if inp.slope_i is not None and inp.slope_i > 0 and inp.n_unpr > 0:
        y_u, v_u, yD_u, Qf_u, Qm_u, ch_u, ca_u, fch, fca, notes_u = solve_unpressurized(
            inp.Q, D, inp.n_unpr, inp.slope_i
        )

    return DiameterCandidate(
        D=D,
        V_press=V_press,
        hf_friction_km=hf_friction_km,
        hf_local_km=hf_local_km,
        hf_total_km=hf_total_km,
        h_loss_total_m=h_loss_total_m,
        increase_pct=pct,
        Q_increased=Q_inc,
        hf_friction_lower_km=hf_friction_lower_km,
        hf_local_lower_km=hf_local_lower_km,
        hf_total_lower_km=hf_total_lower_km,
        h_loss_total_lower_m=h_loss_total_lower_m,
        y_unpr=y_u,
        v_unpr=v_u,
        y_D_ratio=yD_u,
        Q_full_unpr=Qf_u,
        Q_max_unpr=Qm_u,
        clearance_h=ch_u,
        clearance_a_pct=ca_u,
        flag_clr_h=fch,
        flag_clr_a=fca,
        unpr_notes=notes_u,
        category=category,
        flags=flags,
        hydraulic_inner_diameter_mm=(
            pe_spec.hydraulic_inner_diameter_mm if pe_spec is not None
            else product_spec.hydraulic_inner_diameter_mm if product_spec is not None
            else D * 1000.0
        ),
        nominal_outer_diameter_mm=(
            pe_spec.nominal_outer_diameter_mm if pe_spec is not None else None
        ),
        nominal_wall_thickness_mm=(
            pe_spec.nominal_wall_thickness_mm if pe_spec is not None
            else product_spec.nominal_wall_thickness_mm if product_spec is not None
            else None
        ),
        pe_material_grade=pe_spec.grade if pe_spec is not None else None,
        pe_sdr=pe_spec.sdr if pe_spec is not None else None,
        pe_nominal_pressure_mpa=pe_spec.pn_mpa if pe_spec is not None else None,
        product_standard=(
            pe_spec.standard if pe_spec is not None
            else product_spec.product_standard if product_spec is not None
            else None
        ),
        material_key=inp.material_key,
        product_spec_id=(
            f"PE|{pe_spec.grade}|PN{pe_spec.pn_mpa:g}|dn{pe_spec.nominal_outer_diameter_mm}"
            if pe_spec is not None
            else product_spec.spec_id if product_spec is not None
            else None
        ),
        product_family=(
            "PE" if pe_spec is not None
            else product_spec.family if product_spec is not None
            else None
        ),
        product_variant=product_spec.variant if product_spec is not None else None,
        nominal_symbol=(
            "DN" if pe_spec is not None
            else product_spec.nominal_symbol if product_spec is not None
            else None
        ),
        nominal_basis=(
            "公称外径" if pe_spec is not None
            else product_spec.nominal_basis if product_spec is not None
            else None
        ),
        hydraulic_inner_diameter_basis=(
            "DN-2en 名义换算" if pe_spec is not None
            else product_spec.hydraulic_inner_diameter_basis
            if product_spec is not None else None
        ),
        nominal_diameter_mm=(
            float(pe_spec.nominal_outer_diameter_mm) if pe_spec is not None
            else float(product_spec.nominal_diameter_mm) if product_spec is not None
            else None
        ),
        outer_diameter_mm=(
            float(pe_spec.nominal_outer_diameter_mm) if pe_spec is not None
            else product_spec.outer_diameter_mm if product_spec is not None
            else None
        ),
        class_system=(
            "SDR" if pe_spec is not None
            else product_spec.class_system if product_spec is not None
            else None
        ),
        class_code=(
            f"SDR{pe_spec.sdr:g}" if pe_spec is not None
            else product_spec.class_code if product_spec is not None
            else None
        ),
        lining_code=product_spec.lining_code if product_spec is not None else None,
        lining_thickness_mm=(
            product_spec.lining_thickness_mm if product_spec is not None else None
        ),
        minimum_inner_diameter_mm=(
            product_spec.minimum_inner_diameter_mm if product_spec is not None else None
        ),
        maximum_inner_diameter_mm=(
            product_spec.maximum_inner_diameter_mm if product_spec is not None else None
        ),
        selected_inner_diameter_tolerance_mm=(
            product_spec.selected_inner_diameter_tolerance_mm
            if product_spec is not None else None
        ),
        product_standard_references=(
            (pe_spec.standard,) if pe_spec is not None
            else product_spec.standard_references if product_spec is not None
            else ()
        ),
        product_source_locator=product_spec.source_locator if product_spec is not None else None,
    )


_CAT_ORDER = {"经济": 0, "妥协": 1, "兜底": 2}


def _candidate_dimension_key(candidate: DiameterCandidate) -> float:
    """返回用于造价优先排序的公称产品尺寸，旧结果回退水力内径。"""
    if candidate.nominal_diameter_mm is not None:
        return float(candidate.nominal_diameter_mm)
    if candidate.nominal_outer_diameter_mm is not None:
        return float(candidate.nominal_outer_diameter_mm)
    return candidate.D * 1000.0


def _candidate_identity(candidate: DiameterCandidate) -> tuple:
    """返回候选规格稳定标识，材料键参与不同摩阻预设的身份区分。"""
    if candidate.product_spec_id:
        return (candidate.material_key, candidate.product_spec_id)
    if candidate.nominal_outer_diameter_mm is not None:
        return (
            "PE",
            candidate.pe_material_grade,
            candidate.pe_nominal_pressure_mpa,
            candidate.pe_sdr,
            candidate.nominal_outer_diameter_mm,
        )
    return ("D", round(candidate.D, 9))


def _format_candidate_size(candidate: DiameterCandidate) -> str:
    """生成推荐原因和日志使用的规格摘要。"""
    if candidate.product_family == "STEEL":
        return (
            f"钢管公称外径DN{candidate.outer_diameter_mm:g}×{candidate.nominal_wall_thickness_mm:g} mm"
            f"（构造最小壁厚），单侧内衬{candidate.lining_thickness_mm:g} mm，"
            f"水力内径{candidate.hydraulic_inner_diameter_mm:g} mm"
        )
    if candidate.nominal_outer_diameter_mm is not None:
        return (
            f"{candidate.pe_material_grade} DN{candidate.nominal_outer_diameter_mm}×"
            f"{candidate.nominal_wall_thickness_mm:g} mm，SDR{candidate.pe_sdr:g}，"
            f"PN{candidate.pe_nominal_pressure_mpa:g} MPa，"
            f"名义计算内径 di={candidate.hydraulic_inner_diameter_mm:g} mm"
        )
    if candidate.product_family == "DI":
        return (
            f"DN{candidate.nominal_diameter_mm:g}，{candidate.class_code}，"
            f"DE{candidate.outer_diameter_mm:g}×e{candidate.nominal_wall_thickness_mm:g} mm，"
            f"水泥砂浆内衬{candidate.lining_thickness_mm:g} mm，"
            f"名义换算 di={candidate.hydraulic_inner_diameter_mm:g} mm"
        )
    if candidate.product_family == "PCCP":
        return f"{candidate.product_variant} DN={candidate.nominal_diameter_mm:g} mm"
    if candidate.product_family == "FRPM":
        return (
            f"内径系列 DN{candidate.nominal_diameter_mm:g}，"
            f"名义水力内径 di={candidate.hydraulic_inner_diameter_mm:g} mm"
        )
    return f"D={candidate.D:.3f} m"


def _auto_recommend(candidates):
    """从 candidates 中按经济→妥协→兜底规则选出自动推荐结果，返回 (rec, category)"""
    eco = sorted([c for c in candidates if c.category == "经济"], key=_candidate_dimension_key)
    comp = sorted([c for c in candidates if c.category == "妥协"], key=_candidate_dimension_key)
    if eco:
        return eco[0], "经济"
    if comp:
        return comp[0], "妥协"
    fb = sorted(
        candidates,
        key=lambda c: (abs(c.V_press - 0.9), _candidate_dimension_key(c), c.hf_total_km),
    )
    if fb:
        return fb[0], "兜底"
    return None, "无可用"


def _order_for_display(top: List["DiameterCandidate"], recommended: "DiameterCandidate") -> List["DiameterCandidate"]:
    """候选展示排序：推荐项固定首位，其余按类别与总水损排序。"""
    rec_id = _candidate_identity(recommended)
    others = [c for c in top if _candidate_identity(c) != rec_id]
    others_sorted = sorted(
        others,
        key=lambda c: (_CAT_ORDER.get(c.category, 9), c.hf_total_km),
    )
    return [recommended] + others_sorted


def _steel_specs(config, traces):
    """批量默认用整百外径，并按本批流量所需的最大外径扩展扫描范围。"""
    if config.steel_dimension_basis != 'outer':
        raise ValueError('钢管批量计算只接受公称外径，历史内径请先换算')
    diameters = config.steel_diameter_candidates_mm
    if diameters is not None:
        # 显式批量序列保留旧脚本的扫描能力；新界面不再提供自定义候选输入。
        return get_steel_pipe_specs(diameters, 'outer', config.steel_lining_thickness_mm)
    upper = max(3000, max((t['recommended_outer_mm'] for t in traces.values()), default=0) + 400)
    specs = []
    for diameter in range(STEEL_DIAMETER_STEP_MM, int(min(upper, STEEL_MAX_INNER_MM)) + 1, STEEL_DIAMETER_STEP_MM):
        try:
            specs.append(get_steel_pipe_spec(diameter, 'outer', config.steel_lining_thickness_mm))
        except ValueError:
            # 自动扫描不生成内衬占满或超过规范适用范围的尺寸；显式输入仍在上方逐项报错。
            continue
    return tuple(specs)


def recommend_diameter(inp: PressurePipeInput) -> RecommendationResult:
    """
    推荐管径算法：
    1. 筛选"经济区"(0.9<=V<=1.5 且 hf_total<=5)，取最小 D
    2. 若无，筛选"妥协区"(0.6<=V<0.9 且 hf_total<=5)，取最小 D
    3. 若仍无，按 |V-0.9| 最小 + hf_total 最小 兜底
    返回前 5 候选（获胜类别优先，不足时从其他类别补足）。

    产品目录模式按各材料规范离散规格遍历，并以公称产品尺寸作为造价优先排序，
    以目录给出的公称内径或名义换算内径完成全部水力计算。

    当用户指定管径时：
    - PE 使用 manual_nominal_diameter_mm，且只接受所选等级/PN 下的合法 DN；
    - 旧项目仅有 manual_D 时，将其视为原水力内径，并安全上取到 di 不小于旧值的首个标准规格；
    - DI/PCCP/FRPM 使用 manual_product_diameter_mm；目录模式下的旧 manual_D 同样安全上取；
    - 钢管尺寸模式用 manual_steel_diameter_mm；未启用尺寸模式的旧调用继续用 manual_D；
    - 仍遍历标准候选生成对比表；
    - auto_recommended 存储自动推荐结果供对比
    """
    if inp.material_key not in PIPE_MATERIALS:
        return RecommendationResult(
            recommended=None,
            top_candidates=[],
            category="无可用",
            reason=f"未知管材: {inp.material_key}",
            calc_steps="无法完成计算",
        )
    # 在逐规格扫描之前校验，不能把输入错误吞掉后仍返回推荐结果。
    _validate_pressure_pipe_input(inp)
    is_steel = inp.material_key == "钢管" and inp.steel_dimensions_enabled
    if is_steel:
        return recommend_steel_pipe(inp, sys.modules[__name__])
    candidates = []
    material = PIPE_MATERIALS[inp.material_key]
    is_pe = bool(material.get("uses_pe_catalog"))
    catalog_family = material.get("catalog_family")
    uses_product_catalog = bool(catalog_family and inp.use_product_catalog)
    pe_specs: tuple[PEPipeSpec, ...] = ()
    product_specs: tuple[PipeProductSpec, ...] = ()
    if is_pe:
        pe_specs = get_pe_pipe_specs(inp.pe_material_grade, inp.pe_nominal_pressure_mpa)
        for spec in pe_specs:
            try:
                candidates.append(
                    evaluate_single_diameter(inp, spec.inner_diameter_m, pe_spec=spec)
                )
            except ValueError:
                continue
    elif uses_product_catalog:
        product_specs = get_pipe_product_specs(
            inp.material_key,
            ductile_iron_class=inp.ductile_iron_class,
            pccp_variant=inp.pccp_variant,
        )
        for spec in product_specs:
            try:
                candidates.append(
                    evaluate_single_diameter(inp, spec.inner_diameter_m, product_spec=spec)
                )
            except ValueError:
                continue
    else:
        for D in DEFAULT_DIAMETER_SERIES:
            try:
                candidates.append(evaluate_single_diameter(inp, float(D)))
            except ValueError:
                continue

    # ---- 用户指定管径模式 ----
    requested_pe_dn = inp.manual_nominal_diameter_mm
    legacy_pe_inner_diameter_m = None
    requested_product_dn = inp.manual_product_diameter_mm
    legacy_product_inner_diameter_m = None
    if is_pe and inp.manual_D is not None:
        try:
            legacy_pe_inner_diameter_m = float(inp.manual_D)
        except (TypeError, ValueError) as exc:
            raise ValueError("旧版 PE 水力内径 D 必须是数值，单位为 m") from exc
        if not math.isfinite(legacy_pe_inner_diameter_m) or legacy_pe_inner_diameter_m <= 0:
            raise ValueError("旧版 PE 水力内径 D 必须是大于 0 的有限数值")
    if uses_product_catalog and inp.manual_D is not None:
        try:
            legacy_product_inner_diameter_m = float(inp.manual_D)
        except (TypeError, ValueError) as exc:
            raise ValueError("旧版水力内径 D 必须是数值，单位为 m") from exc
        if not math.isfinite(legacy_product_inner_diameter_m) or legacy_product_inner_diameter_m <= 0:
            raise ValueError("旧版水力内径 D 必须是大于 0 的有限数值")
    has_manual = (
        (is_pe and (requested_pe_dn is not None or legacy_pe_inner_diameter_m is not None))
        or (
            uses_product_catalog
            and (requested_product_dn is not None or legacy_product_inner_diameter_m is not None)
        )
        or (
            not is_pe and not uses_product_catalog
            and inp.manual_D is not None and inp.manual_D > 0
        )
    )
    if has_manual:
        manual_candidate = None
        if is_pe:
            if requested_pe_dn is not None:
                requested_spec = get_pe_pipe_spec(
                    inp.pe_material_grade,
                    inp.pe_nominal_pressure_mpa,
                    requested_pe_dn,
                )
                if (
                    legacy_pe_inner_diameter_m is not None
                    and requested_spec.inner_diameter_m + 1e-9 < legacy_pe_inner_diameter_m
                ):
                    raise ValueError(
                        f"迁移后的 PE 规格名义内径 {requested_spec.inner_diameter_m:g} m "
                        f"小于旧项目水力内径 {legacy_pe_inner_diameter_m:g} m"
                    )
            else:
                requested_spec = next(
                    (
                        spec for spec in pe_specs
                        if spec.inner_diameter_m + 1e-9 >= legacy_pe_inner_diameter_m
                    ),
                    None,
                )
                if requested_spec is None:
                    raise ValueError(
                        f"旧项目 PE 水力内径 D={legacy_pe_inner_diameter_m:g} m 超出"
                        f"所选 {inp.pe_material_grade}、PN {inp.pe_nominal_pressure_mpa:g} MPa "
                        "标准规格的可迁移范围"
                    )
            manual_candidate = next(
                (
                    c for c in candidates
                    if c.nominal_outer_diameter_mm == requested_spec.nominal_outer_diameter_mm
                ),
                None,
            )
        elif uses_product_catalog:
            if requested_product_dn is not None:
                requested_product_spec = get_pipe_product_spec(
                    inp.material_key,
                    requested_product_dn,
                    ductile_iron_class=inp.ductile_iron_class,
                    pccp_variant=inp.pccp_variant,
                )
                if (
                    legacy_product_inner_diameter_m is not None
                    and requested_product_spec.inner_diameter_m + 1e-9
                    < legacy_product_inner_diameter_m
                ):
                    raise ValueError(
                        f"迁移后的产品规格名义内径 {requested_product_spec.inner_diameter_m:g} m "
                        f"小于旧项目水力内径 {legacy_product_inner_diameter_m:g} m"
                    )
            else:
                requested_product_spec = next(
                    (
                        spec for spec in product_specs
                        if spec.inner_diameter_m + 1e-9 >= legacy_product_inner_diameter_m
                    ),
                    None,
                )
                if requested_product_spec is None:
                    raise ValueError(
                        f"旧项目水力内径 D={legacy_product_inner_diameter_m:g} m "
                        "超出当前产品目录可迁移范围"
                    )
            manual_candidate = next(
                (
                    candidate for candidate in candidates
                    if candidate.product_spec_id == requested_product_spec.spec_id
                ),
                None,
            )
        else:
            manual_D_val = float(inp.manual_D)
            for c in candidates:
                if abs(c.D - manual_D_val) < 1e-6:
                    manual_candidate = c
                    break
            # 非 PE 保留既有自定义水力内径能力。
            if manual_candidate is None:
                manual_candidate = evaluate_single_diameter(inp, manual_D_val)
                manual_candidate.flags.append("非标准管径")
                candidates.append(manual_candidate)
        if manual_candidate is not None:
            fallback_sorted = sorted(
                candidates,
                key=lambda c: (abs(c.V_press - 0.9), _candidate_dimension_key(c), c.hf_total_km),
            )
            # 自动推荐结果（在追加"用户指定"标记之前调用，避免同对象污染）
            auto_rec, auto_cat = _auto_recommend(candidates)
            if legacy_pe_inner_diameter_m is not None:
                manual_candidate.flags.append(
                    f"旧版水力内径 {legacy_pe_inner_diameter_m:g} m 已安全上取为标准规格"
                )
            if legacy_product_inner_diameter_m is not None:
                manual_candidate.flags.append(
                    f"旧版水力内径 {legacy_product_inner_diameter_m:g} m 已安全上取为标准规格"
                )
            manual_candidate.flags.append("用户指定")
            # top: 指定D排首位，其余按原排序补足
            top5 = [manual_candidate]
            seen_ids = {_candidate_identity(manual_candidate)}
            for c in fallback_sorted:
                identity = _candidate_identity(c)
                if identity not in seen_ids:
                    top5.append(c)
                    seen_ids.add(identity)
                    if len(top5) >= 5:
                        break
            top5 = _order_for_display(top5, manual_candidate)
            reason_prefix = (
                "旧项目规格迁移"
                if legacy_pe_inner_diameter_m is not None
                or legacy_product_inner_diameter_m is not None
                else "用户指定"
            )
            reason = (f"{reason_prefix}: {_format_candidate_size(manual_candidate)}, "
                      f"V={manual_candidate.V_press:.3f}m/s, "
                      f"hf_total={manual_candidate.hf_total_km:.4f}m/km "
                      f"({manual_candidate.category})")
            calc_text = _build_process_text(inp, candidates, manual_candidate, "指定",
                                            auto_rec=auto_rec, auto_cat=auto_cat)
            return RecommendationResult(
                recommended=manual_candidate, top_candidates=top5,
                category="指定", reason=reason, calc_steps=calc_text,
                auto_recommended=auto_rec,
            )

    if not candidates:
        return RecommendationResult(
            recommended=None,
            top_candidates=[],
            category="无可用",
            reason="所有口径均计算失败",
            calc_steps="无法完成计算",
        )

    # 各类别分组
    eco = sorted([c for c in candidates if c.category == "经济"], key=_candidate_dimension_key)
    comp = sorted([c for c in candidates if c.category == "妥协"], key=_candidate_dimension_key)
    fallback_sorted = sorted(
        candidates,
        key=lambda c: (abs(c.V_press - 0.9), _candidate_dimension_key(c), c.hf_total_km),
    )

    def _fill_top5(primary, all_sorted):
        """获胜类别优先，不足5个时从全体候选补足并按稳定规格去重。"""
        top = list(primary[:5])
        if len(top) < 5:
            seen_ids = {_candidate_identity(c) for c in top}
            for c in all_sorted:
                identity = _candidate_identity(c)
                if identity not in seen_ids:
                    top.append(c)
                    seen_ids.add(identity)
                    if len(top) >= 5:
                        break
        return top

    # ---- 自动推荐模式（原逻辑） ----

    # 第一步：经济区
    if eco:
        rec = eco[0]
        top5 = _order_for_display(_fill_top5(eco, fallback_sorted), rec)
        reason = f"经济优先: {_format_candidate_size(rec)}, V={rec.V_press:.3f}m/s, hf_total={rec.hf_total_km:.4f}m/km"
        calc_text = _build_process_text(inp, candidates, rec, "经济")
        return RecommendationResult(
            recommended=rec, top_candidates=top5,
            category="经济", reason=reason, calc_steps=calc_text,
        )

    # 第二步：妥协区
    if comp:
        rec = comp[0]
        top5 = _order_for_display(_fill_top5(comp, fallback_sorted), rec)
        reason = f"妥协兜底: {_format_candidate_size(rec)}, V={rec.V_press:.3f}m/s, hf_total={rec.hf_total_km:.4f}m/km"
        calc_text = _build_process_text(inp, candidates, rec, "妥协")
        return RecommendationResult(
            recommended=rec, top_candidates=top5,
            category="妥协", reason=reason, calc_steps=calc_text,
        )

    # 第三步：兜底
    rec = fallback_sorted[0]
    rec.flags.append("未满足约束")
    top5 = _order_for_display(fallback_sorted[:5], rec)
    reason = f"就近流速兜底: {_format_candidate_size(rec)}, V={rec.V_press:.3f}m/s, hf_total={rec.hf_total_km:.4f}m/km (未满足约束)"
    calc_text = _build_process_text(inp, candidates, rec, "兜底")
    return RecommendationResult(
        recommended=rec, top_candidates=top5,
        category="兜底", reason=reason, calc_steps=calc_text,
    )


def build_detailed_process_text(inp: PressurePipeInput, recommendation: RecommendationResult) -> str:
    """供外部调用的详细过程文本（直接返回 calc_steps）"""
    return recommendation.calc_steps


# ============================================================
# 4. 批量扫描
# ============================================================


def _safe_savefig(fig, path, **kwargs):
    """保存图片，处理 Windows 文件锁定：若被占用则追加编号另存"""
    try:
        fig.savefig(path, **kwargs)
        return path
    except PermissionError:
        pass
    for attempt in range(1, 100):
        target = _numbered_path(path, attempt)
        try:
            fig.savefig(target, **kwargs)
            return target
        except PermissionError:
            continue
    # 最终回退：带时间戳
    import time
    base, ext = os.path.splitext(path)
    fallback = f"{base}_{int(time.time())}{ext}"
    fig.savefig(fallback, **kwargs)
    return fallback


def _numbered_path(path, n):
    base, ext = os.path.splitext(path)
    return f"{base}_{n}{ext}"


def _setup_adaptive_xaxis(ax, d_data, fontsize=None):
    """自适应X轴：裁剪到数据范围，在数据点D值位置标刻度"""
    d_unique = sorted(set(d_data))
    if not d_unique:
        return
    pad = max(0.05, (d_unique[-1] - d_unique[0]) * 0.03)
    ax.set_xlim(d_unique[0] - pad, d_unique[-1] + pad)
    ax.set_xticks(d_unique)
    labels = [f"{d:.2f}" if abs(d - round(d, 1)) > 1e-9 else f"{d:.1f}"
              for d in d_unique]
    rot = 45 if len(d_unique) > 12 else 0
    ha = 'right' if rot else 'center'
    fs = fontsize or (8 if len(d_unique) > 15 else 9)
    ax.set_xticklabels(labels, fontsize=fs, rotation=rot, ha=ha)
    ax.grid(True, which="major", linestyle="-", linewidth=0.8, alpha=0.5)


def run_batch_scan(
    config: BatchScanConfig,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    cancel_flag: Optional[Callable[[], bool]] = None,
) -> BatchScanResult:
    """
    批量扫描：遍历 Q × 坡度 × 材料规格，生成 CSV、PNG、PDF 和合并 PDF。

    ``diameter_values=None`` 时按材料取规格：PE、DI、PCCP、FRPM 使用各自
    产品目录，其他管材使用既有通用水力内径序列；显式数组始终保留旧接口行为。

    progress_cb(current, total, message): 进度回调
    cancel_flag(): 返回 True 时中止
    """
    import matplotlib
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import seaborn as sns
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MultipleLocator

    # 输出前整批校验；一条无效输入也不得产生部分有效、部分无效的 CSV。
    _validate_hydraulic_number(config.length_m, "管长 L")
    _validate_hydraulic_number(config.local_loss_ratio, "局部损失比例", allow_zero=True)
    for q_value in config.q_values:
        _validate_hydraulic_number(q_value, "设计流量 Q")
    for denominator in config.slope_denominators:
        _validate_hydraulic_number(denominator, "坡度分母")
    if config.slope_denominators:
        _validate_hydraulic_number(config.n_unpr, "无压糙率 n")
        for value, label in ((config.unpr_clearance_height, "项目净空高度"), (config.unpr_clearance_area, "项目净空面积")):
            if value is not None:
                _validate_hydraulic_number(value, label, allow_zero=True)
        if config.unpr_clearance_area is not None and config.unpr_clearance_area > 100:
            raise ValueError("项目净空面积不能超过 100%")
    if config.diameter_values is not None:
        for diameter in config.diameter_values:
            _validate_hydraulic_number(diameter, "管径 D")
    steel_specs = ()
    steel_traces = {}
    if "钢管" in config.materials and config.steel_dimensions_enabled:
        if config.diameter_values is not None:
            raise ValueError("钢管尺寸模式统一扫描公称外径，不能同时传入旧水力内径序列")
        _validate_hydraulic_number(config.steel_lining_thickness_mm, '单侧内衬厚度', allow_zero=True)
        for q_value in config.q_values:
            q_value = float(q_value)
            required = steel_hydraulic_requirement(q_value, q_value * (1 + get_flow_increase_percent(q_value) / 100),
                                                    PIPE_MATERIALS['钢管'], ECONOMIC_RULE, config.local_loss_ratio)
            steel_traces[q_value], _ = select_steel_outer_diameter(required, config.steel_lining_thickness_mm)
        steel_specs = _steel_specs(config, steel_traces)

    result = BatchScanResult()
    output_dir = config.output_dir
    if not output_dir:
        result.logs.append("错误: 未指定输出目录")
        return result

    os.makedirs(output_dir, exist_ok=True)

    # ---- P95 自适应 Y 轴辅助函数 ----
    def _percentile_ylim(values, percentile=95, margin=1.2, floor=0.6):
        """取分位数 × margin 作为Y轴上限，不低于 floor"""
        if len(values) == 0:
            return floor
        p = np.percentile(values, percentile)
        return max(floor, p * margin)

    # ---- 配置绘图样式 ----
    sns.set_theme(style="whitegrid")
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun']
    plt.rcParams['axes.unicode_minus'] = False

    # 无压对比模式：有坡度数据时按坡度遍历；否则单次迭代仅做有压计算
    _has_unpr = bool(config.slope_denominators)
    if _has_unpr:
        slope_values = [1.0 / d for d in config.slope_denominators]
        slope_labels = [f"1/{d}" for d in config.slope_denominators]
    else:
        slope_values = [None]   # 单次占位，slope_i=None → 跳过无压计算
        slope_labels = ["N/A"]

    # ---- 阶段1: 计算并保存 CSV ----
    results_list = []
    def _scan_entries_for_material(
        mat_key: str,
    ) -> list[tuple[float, Optional[PEPipeSpec], Optional[PipeProductSpec]]]:
        """按材料返回批量计算的水力内径及可选产品规格。"""
        if config.diameter_values is not None:
            # 显式传入管径时保留旧接口语义，便于历史脚本和回归测试继续运行。
            return [(float(diameter), None, None) for diameter in config.diameter_values]
        material = PIPE_MATERIALS[mat_key]
        if mat_key == "钢管" and config.steel_dimensions_enabled:
            return [(spec.inner_diameter_m, None, spec) for spec in steel_specs]
        if material.get("uses_pe_catalog"):
            return [
                (spec.inner_diameter_m, spec, None)
                for spec in get_pe_pipe_specs(
                    config.pe_material_grade,
                    config.pe_nominal_pressure_mpa,
                )
            ]
        if material.get("catalog_family") and config.use_product_catalogs:
            return [
                (spec.inner_diameter_m, None, spec)
                for spec in get_pipe_product_specs(
                    mat_key,
                    ductile_iron_class=config.ductile_iron_class,
                    pccp_variant=config.pccp_variant,
                )
            ]
        return [(float(diameter), None, None) for diameter in DEFAULT_DIAMETER_SERIES]

    scan_entries_by_material = {
        mat_key: _scan_entries_for_material(mat_key)
        for mat_key in config.materials
        if mat_key in PIPE_MATERIALS
    }
    total = (
        len(config.q_values)
        * len(slope_values)
        * sum(len(entries) for entries in scan_entries_by_material.values())
    )
    count = 0

    # 进度条分段: 计算 0-30%, 绘图 30-95%, 合并 95-100%
    _TOTAL_STEPS = 1000
    _PHASE1_END = 300
    _PHASE2_END = 950
    _update_interval = max(1, total // 100)

    for mat_key in config.materials:
        if mat_key not in PIPE_MATERIALS:
            result.logs.append(f"跳过未知管材: {mat_key}")
            continue
        mat = PIPE_MATERIALS[mat_key]
        mat_name = mat["name"]

        scan_entries = scan_entries_by_material[mat_key]
        for Q in config.q_values:
            for si, i_val in enumerate(slope_values):
                for D, pe_spec, product_spec in scan_entries:
                    if cancel_flag and cancel_flag():
                        result.logs.append("用户取消")
                        return result

                    count += 1
                    if progress_cb and count % _update_interval == 0:
                        progress_cb(
                            int(count / total * _PHASE1_END),
                            _TOTAL_STEPS,
                            f"计算中 {mat_name} Q={Q:g} ({count}/{total})",
                        )

                    inp = PressurePipeInput(
                        Q=float(Q), material_key=mat_key,
                        slope_i=i_val, n_unpr=config.n_unpr,
                        length_m=config.length_m,
                        local_loss_ratio=config.local_loss_ratio,
                        pe_material_grade=config.pe_material_grade,
                        pe_nominal_pressure_mpa=config.pe_nominal_pressure_mpa,
                        use_product_catalog=config.use_product_catalogs,
                        ductile_iron_class=config.ductile_iron_class,
                        pccp_variant=config.pccp_variant,
                    )
                    try:
                        c = evaluate_single_diameter(
                            inp,
                            float(D),
                            pe_spec=pe_spec,
                            product_spec=product_spec,
                        )
                    except ValueError:
                        continue

                    if c.product_family == 'STEEL':
                        c.steel_sizing_trace = dict(steel_traces[float(Q)])

                    if _has_unpr:
                        comparison = compare_flows(c, float(Q), config.slope_denominators[si], config.n_unpr,
                                                   config.unpr_clearance_height, config.unpr_clearance_area)
                        for row in comparison:
                            # 按同一材料公式还原设计流量损失，加大工况直接采用候选值。
                            loss_scale = (row['flow'] / (float(Q) * (1 + c.increase_pct / 100))) ** mat['m']
                            row.update(material=mat.get('display_name', mat_name), specification=_format_candidate_size(c),
                                       pressure_loss=c.hf_total_km * loss_scale,
                                       pressure_loss_lower=c.hf_total_lower_km * loss_scale if c.hf_total_lower_km is not None else None,
                                       category=c.category)
                        result.comparison_rows.extend(comparison)

                    results_list.append({
                        "管材类型": mat_name,
                        "f采用值（上限）": mat["f"],
                        "f下限": mat.get("f_min", ""),
                        "Q_target (m\u00b3/s)": float(Q),
                        "n_unpr": config.n_unpr if _has_unpr else "",
                        "i_unpr_str": slope_labels[si],
                        "i_unpr_val": i_val if i_val is not None else "",
                        # D (m) 为兼容列，语义统一为实际代入公式的水力计算内径。
                        "D (m)": c.D,
                        "水力计算内径 di (mm)": c.hydraulic_inner_diameter_mm,
                        "公称外径 DN (mm)": c.nominal_outer_diameter_mm or "",
                        "公称壁厚 en (mm)": (
                            c.nominal_wall_thickness_mm
                            if c.product_family == "PE" else ""
                        ),
                        "PE材料等级": c.pe_material_grade or "",
                        "PE公称压力 PN (MPa)": c.pe_nominal_pressure_mpa or "",
                        "PE标准尺寸比 SDR": c.pe_sdr or "",
                        "产品标准": c.product_standard or "",
                        "y_unpr (m)": c.y_unpr,
                        "v_unpr (m/s)": c.v_unpr,
                        "y/D_unpr": c.y_D_ratio,
                        "V_press (m/s)": c.V_press,
                        "hf_press (m/km)": c.hf_friction_km,
                        "hf_local_press (m/km)": c.hf_local_km,
                        "hf_total_press (m/km)": c.hf_total_km,
                        "h_loss_total (m)": c.h_loss_total_m,
                        "hf_press_f下限 (m/km)": (
                            c.hf_friction_lower_km
                            if c.hf_friction_lower_km is not None else ""
                        ),
                        "hf_local_press_f下限 (m/km)": (
                            c.hf_local_lower_km
                            if c.hf_local_lower_km is not None else ""
                        ),
                        "hf_total_press_f下限 (m/km)": (
                            c.hf_total_lower_km
                            if c.hf_total_lower_km is not None else ""
                        ),
                        "h_loss_total_f下限 (m)": (
                            c.h_loss_total_lower_m
                            if c.h_loss_total_lower_m is not None else ""
                        ),
                        "净空高度 (m)": c.clearance_h,
                        "净空面积 (%)": c.clearance_a_pct,
                        "净空高<0.4m": c.flag_clr_h,
                        "净空面积(%)<15": c.flag_clr_a,
                        "Q_full_unpr (m\u00b3/s)": c.Q_full_unpr,
                        "Q_max_unpr (m\u00b3/s)": c.Q_max_unpr,
                        "加大比例 (%)": c.increase_pct,
                        "分类": c.category,
                        "备注": c.unpr_notes,
                        # 通用产品字段只在末尾追加，保留既有 CSV 列名与顺序。
                        "产品族": c.product_family or "",
                        "产品型式": c.product_variant or "",
                        "产品规格ID": c.product_spec_id or "",
                        "公称口径代号": c.nominal_symbol or "",
                        "公称口径 (mm)": c.nominal_diameter_mm or "",
                        "口径基准": c.nominal_basis or "",
                        "产品外径 (mm)": c.outer_diameter_mm or "",
                        "产品公称壁厚 (mm)": c.nominal_wall_thickness_mm or "",
                        "水力内径取值依据": c.hydraulic_inner_diameter_basis or "",
                        "等级体系": c.class_system or "",
                        "等级代码": c.class_code or "",
                        "内衬代号": c.lining_code or "",
                        "内衬厚度 (mm)": c.lining_thickness_mm if c.lining_thickness_mm is not None else "",
                        "两端最小内径 (mm)": c.minimum_inner_diameter_mm or "",
                        "两端最大内径 (mm)": c.maximum_inner_diameter_mm or "",
                        "设计内径允许偏差 (mm)": c.selected_inner_diameter_tolerance_mm or "",
                        "产品规格依据": "、".join(c.product_standard_references),
                        "规格表定位": c.product_source_locator or "",
                        "钢管壁厚选取": c.class_code if c.product_family == "STEEL" else "",
                        "钢管尺寸计算过程": "；".join(steel_sizing_process(c.steel_sizing_trace) + steel_dimension_process(c)) if c.product_family == "STEEL" else "",
                        "钢管所需最小水力内径 (mm)": (c.steel_sizing_trace or {}).get('required_hydraulic_inner_mm', ''),
                        "钢管上取公称外径 DN (mm)": (c.steel_sizing_trace or {}).get('recommended_outer_mm', ''),
                        "钢管最小推荐档": bool(c.steel_sizing_trace and c.outer_diameter_mm == c.steel_sizing_trace['recommended_outer_mm'] and c.category != '兜底'),
                    })

    if progress_cb:
        progress_cb(_PHASE1_END, _TOTAL_STEPS, "计算完成，保存CSV...")

    if result.comparison_rows and config.output_csv:
        comparison_path = os.path.join(output_dir, "无压输水能力对比明细.csv")
        pd.DataFrame(result.comparison_rows).reindex(columns=COMPARISON_COLUMNS).rename(columns=COMPARISON_COLUMNS).to_csv(
            comparison_path, index=False, encoding="utf-8-sig")
        result.comparison_csv_path = comparison_path
        result.logs.append(f"同流量无压对比明细已保存: {comparison_path}")
    if result.comparison_rows:
        result.logs.append("对比页与专用明细按设计/加大流量分别对齐；原有批量CSV中有压水损仍为加大流量，旧净空标记仅供兼容。")

    df = pd.DataFrame(results_list)
    csv_name = "有压管道批量计算结果.csv"
    csv_path = os.path.join(output_dir, csv_name)
    if config.output_csv:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        result.csv_path = csv_path
        result.logs.append(f"CSV 已保存: {csv_path}")
    else:
        result.logs.append("已跳过 CSV 输出（配置为关闭）")

    if df.empty:
        result.logs.append("无有效计算数据，跳过绘图")
        return result

    # 如果 PDF 和 PNG 都关闭，则跳过绘图阶段
    if not config.output_pdf_charts and not config.output_subplot_png:
        result.logs.append("已跳过绘图输出（PDF和PNG配置均为关闭）")
        return result

    # ---- 阶段2: 绘图 ----
    all_materials = df["管材类型"].unique()

    # 预估绘图总步数
    _chart_total = 0
    for _mn in all_materials:
        _df_m = df[df["管材类型"] == _mn]
        _nq = len(_df_m["Q_target (m³/s)"].unique())
        _chart_total += ((_nq + 9) // 10) * 2  # 图1 + 图2
    _chart_total = max(_chart_total, 1)
    _chart_count = 0
    if progress_cb:
        progress_cb(_PHASE1_END, _TOTAL_STEPS, "开始绘图...")

    for mat_name in all_materials:
        if cancel_flag and cancel_flag():
            result.logs.append("用户取消（绘图阶段）")
            return result

        df_mat = df[df["管材类型"] == mat_name].copy()

        all_Q = sorted(df_mat["Q_target (m\u00b3/s)"].unique())
        safe_mat = mat_name.replace("(", "_").replace(")", "_").replace("=", "_")

        # -- 图1: 无压/有压流速对比 + 水损双轴 (与 V9 一致) --
        df_unpr_valid = df_mat.dropna(subset=["v_unpr (m/s)"]).copy()
        df_press_valid = df_mat.dropna(subset=["V_press (m/s)", "hf_total_press (m/km)"]).copy()

        if not _has_unpr and (not df_unpr_valid.empty or not df_press_valid.empty):
            # 准备坡度分类
            slope_labels_sorted = sorted(
                [s for s in df_mat["i_unpr_str"].unique()
                 if "/" in s and s not in ("N/A", "n/a")],
                key=lambda s: float(s.split("/")[0]) / float(s.split("/")[1])
            )
            num_slopes = len(slope_labels_sorted)
            palette = sns.color_palette("tab10", n_colors=max(num_slopes, 2))
            markers_list = ['o', 's', 'D', '^', 'v', 'P', 'X', '*', 'h']

            chunk_size = 10
            q_chunks_fig1 = [all_Q[j:j + chunk_size] for j in range(0, len(all_Q), chunk_size)]

            for cidx1, qchunk1 in enumerate(q_chunks_fig1):
                if cancel_flag and cancel_flag():
                    result.logs.append("用户取消（图1）")
                    return result

                q_start1 = f"{qchunk1[0]:g}"
                q_end1 = f"{qchunk1[-1]:g}"

                nq1 = len(qchunk1)
                ncol1 = min(5, nq1)
                nrow1 = (nq1 + ncol1 - 1) // ncol1
                fig1 = Figure(figsize=(ncol1 * 7, nrow1 * 5.5))
                FigureCanvasAgg(fig1)
                axes1 = fig1.subplots(nrow1, ncol1, squeeze=False)

                for qi1, q_val1 in enumerate(qchunk1):
                    r1, c1 = divmod(qi1, ncol1)
                    ax1 = axes1[r1][c1]

                    # 绘制无压流速 (按坡度分组)
                    for si_idx, slope_lbl in enumerate(slope_labels_sorted):
                        q_slope_data = df_unpr_valid[
                            (df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1) &
                            (df_unpr_valid["i_unpr_str"] == slope_lbl)
                        ].sort_values("D (m)")
                        if not q_slope_data.empty:
                            ax1.plot(q_slope_data["D (m)"], q_slope_data["v_unpr (m/s)"],
                                     color=palette[si_idx % num_slopes],
                                     marker=markers_list[si_idx % len(markers_list)],
                                     markersize=4, linewidth=1.3, label=slope_lbl if qi1 == 0 else "_nolegend_")

                    # 绘制有压流速 (与坡度无关，去重)
                    q_press_data = df_press_valid[
                        df_press_valid["Q_target (m\u00b3/s)"] == q_val1
                    ].drop_duplicates(subset=["D (m)"]).sort_values("D (m)")
                    if not q_press_data.empty:
                        ax1.plot(q_press_data["D (m)"], q_press_data["V_press (m/s)"],
                                 linestyle=":", color="dimgray", linewidth=1.8, marker=".", markersize=5,
                                 label="V_press (有压)" if qi1 == 0 else "_nolegend_")

                    # y轴范围 (P95自适应)
                    _all_v = []
                    q_unpr_v = df_unpr_valid[df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1]["v_unpr (m/s)"].dropna()
                    if not q_unpr_v.empty:
                        _all_v.extend(q_unpr_v.tolist())
                    if not q_press_data.empty:
                        _all_v.extend(q_press_data["V_press (m/s)"].dropna().tolist())
                    ax1.set_ylim(bottom=0, top=_percentile_ylim(_all_v, floor=0.6))

                    # 右轴: 有压总水损
                    ax2_1 = ax1.twinx()
                    if not q_press_data.empty:
                        hf_color = "firebrick"
                        ax2_1.plot(q_press_data["D (m)"], q_press_data["hf_total_press (m/km)"],
                                   linestyle="--", color=hf_color, linewidth=1.8, marker="x", markersize=4,
                                   alpha=0.8, label="总水损 (右轴)" if qi1 == 0 else "_nolegend_")
                        _d_med = q_press_data["D (m)"].median()
                        _hf_upper = q_press_data.loc[q_press_data["D (m)"] >= _d_med, "hf_total_press (m/km)"].dropna().tolist()
                        ax2_1.set_ylim(bottom=0, top=_percentile_ylim(_hf_upper, floor=0.5))
                        ax2_1.set_ylabel("总水头损失 (m/km)", color=hf_color)
                        ax2_1.tick_params(axis="y", labelcolor=hf_color)
                    else:
                        ax2_1.set_yticks([])

                    ax1.set_xlabel("水力计算内径 (m)")
                    ax1.set_ylabel("流速 (m/s)")
                    ax1.set_title(f"Q = {q_val1:g} {PLOT_FLOW_UNIT_M3_PER_S}")
                    # 自适应X轴
                    _d_q1 = set(df_unpr_valid[df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1]["D (m)"].tolist())
                    if not q_press_data.empty:
                        _d_q1.update(q_press_data["D (m)"].tolist())
                    _setup_adaptive_xaxis(ax1, list(_d_q1))

                # 隐藏多余子图
                for qi1 in range(nq1, nrow1 * ncol1):
                    r1, c1 = divmod(qi1, ncol1)
                    axes1[r1][c1].set_visible(False)

                fig1.suptitle(
                    f"图1: 无压/有压流速与总水损对比 "
                    f"(Q: {q_start1}-{q_end1} {PLOT_FLOW_UNIT_M3_PER_S}, {mat_name})",
                    fontsize=14,
                )
                fig1.tight_layout(rect=[0, 0, 1, 0.95])

                pdf_name1 = f"图1_流速水损对比_{q_start1}_{q_end1}_{safe_mat}.pdf"
                pdf_path1 = os.path.join(output_dir, pdf_name1)
                if config.output_pdf_charts:
                    actual1 = _safe_savefig(fig1, pdf_path1, dpi=150)
                    result.generated_pdfs.append(actual1)
                    result.logs.append(f"PDF: {os.path.basename(actual1)}")

                _chart_count += 1
                if progress_cb:
                    progress_cb(
                        _PHASE1_END + int(_chart_count / _chart_total * ((900 if _has_unpr else _PHASE2_END) - _PHASE1_END)),
                        _TOTAL_STEPS,
                        f"绘图中 ({_chart_count}/{_chart_total}) {pdf_name1}",
                    )

                # 子图 PNG - 为每个Q值创建独立完整的figure
                if config.output_subplot_png:
                    png_dir1 = os.path.join(output_dir, "子图PNG", safe_mat)
                    os.makedirs(png_dir1, exist_ok=True)
                    for qi1, q_val1 in enumerate(qchunk1):
                        # 创建独立figure
                        fig_sub1 = Figure(figsize=(10, 7))
                        FigureCanvasAgg(fig_sub1)
                        ax_sub1 = fig_sub1.add_subplot(111)
                        ax_sub1_twin = ax_sub1.twinx()

                        ax_sub1.set_xlabel("水力计算内径 (m)", fontsize=12)

                        # 绘制无压流速 (按坡度分组)
                        _all_v_sub1 = []
                        for si_idx, slope_lbl in enumerate(slope_labels_sorted):
                            q_slope_data = df_unpr_valid[
                                (df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1) &
                                (df_unpr_valid["i_unpr_str"] == slope_lbl)
                            ].sort_values("D (m)")
                            if not q_slope_data.empty:
                                ax_sub1.plot(q_slope_data["D (m)"], q_slope_data["v_unpr (m/s)"],
                                            color=palette[si_idx % num_slopes],
                                            marker=markers_list[si_idx % len(markers_list)],
                                            markersize=4, linewidth=1.3, label=f"i={slope_lbl} (无压)")
                                _all_v_sub1.extend(q_slope_data["v_unpr (m/s)"].dropna().tolist())

                        # 绘制有压流速
                        q_press_data_sub1 = df_press_valid[
                            df_press_valid["Q_target (m\u00b3/s)"] == q_val1
                        ].drop_duplicates(subset=["D (m)"]).sort_values("D (m)")
                        if not q_press_data_sub1.empty:
                            ax_sub1.plot(q_press_data_sub1["D (m)"], q_press_data_sub1["V_press (m/s)"],
                                        linestyle=":", color="dimgray", linewidth=1.8, marker=".", markersize=5,
                                        label="V_press (有压)")
                            _all_v_sub1.extend(q_press_data_sub1["V_press (m/s)"].dropna().tolist())

                        # 设置左Y轴 (P95自适应)
                        ax_sub1.set_ylabel("流速 (m/s)", fontsize=12)
                        ax_sub1.set_ylim(bottom=0, top=_percentile_ylim(_all_v_sub1, floor=0.6))

                        # 绘制右轴: 有压总水损
                        hf_color_sub1 = "firebrick"
                        if not q_press_data_sub1.empty:
                            ax_sub1_twin.plot(q_press_data_sub1["D (m)"], q_press_data_sub1["hf_total_press (m/km)"],
                                             linestyle="--", color=hf_color_sub1, linewidth=1.8, marker="x", markersize=4,
                                             alpha=0.8, label="总水损 (有压, 右轴)")
                            _d_med_sub1 = q_press_data_sub1["D (m)"].median()
                            _hf_upper_sub1 = q_press_data_sub1.loc[q_press_data_sub1["D (m)"] >= _d_med_sub1, "hf_total_press (m/km)"].dropna().tolist()
                            ax_sub1_twin.set_ylim(bottom=0, top=_percentile_ylim(_hf_upper_sub1, floor=0.5))
                            ax_sub1_twin.set_ylabel("总水头损失 (m/km)", fontsize=11, color=hf_color_sub1)
                            ax_sub1_twin.tick_params(axis="y", labelcolor=hf_color_sub1)
                            ax_sub1_twin.spines["right"].set_edgecolor(hf_color_sub1)
                        else:
                            ax_sub1_twin.set_yticks([])

                        # 自适应X轴
                        _d_sub1 = set(df_unpr_valid[df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1]["D (m)"].tolist())
                        if not q_press_data_sub1.empty:
                            _d_sub1.update(q_press_data_sub1["D (m)"].tolist())
                        _setup_adaptive_xaxis(ax_sub1, list(_d_sub1), fontsize=10)

                        # 设置标题
                        fig_sub1.suptitle(
                            f"图1: 无压/有压流速与总水损对比\n"
                            f"目标流量 Q = {q_val1:g} {PLOT_FLOW_UNIT_M3_PER_S}, 管材: {mat_name}",
                            fontsize=14,
                            y=0.98,
                        )

                        # 合并图例
                        handles_sub1, labels_sub1 = ax_sub1.get_legend_handles_labels()
                        handles_twin1, labels_twin1 = ax_sub1_twin.get_legend_handles_labels()
                        fig_sub1.legend(handles_sub1 + handles_twin1, labels_sub1 + labels_twin1,
                                       loc='upper right', bbox_to_anchor=(0.98, 0.88),
                                       fontsize=8, frameon=True, ncol=2)

                        # 保存
                        fig_sub1.tight_layout(rect=[0, 0, 1, 0.93])
                        png_name1 = f"图1_Q{q_val1:g}_{safe_mat}.png"
                        png_path1 = os.path.join(png_dir1, png_name1)
                        actual_png1 = _safe_savefig(fig_sub1, png_path1, dpi=300, bbox_inches='tight', pad_inches=0.1)
                        result.generated_pngs.append(actual_png1)
                        plt.close(fig_sub1)

                plt.close(fig1)

        # -- 图2: 经济/妥协设计点 --
        df_press = df_mat.dropna(subset=["V_press (m/s)", "hf_total_press (m/km)"]).copy()
        df_press = df_press[["Q_target (m\u00b3/s)", "D (m)", "V_press (m/s)",
                             "hf_total_press (m/km)"]].drop_duplicates()
        df_press["category"] = pd.Series(dtype="object")
        cond_eco = (
            (df_press["V_press (m/s)"] >= 0.9)
            & (df_press["V_press (m/s)"] <= 1.5)
            & (df_press["hf_total_press (m/km)"] <= 5.0)
        )
        cond_comp = (
            (df_press["V_press (m/s)"] >= 0.6)
            & (df_press["V_press (m/s)"] < 0.9)
            & (df_press["hf_total_press (m/km)"] <= 5.0)
        )
        df_press.loc[cond_eco, "category"] = "经济流速 (0.9-1.5 m/s, 总hf <= 5 m/km)"
        df_press.loc[cond_comp, "category"] = "妥协流速 (0.6-0.89 m/s, 总hf <= 5 m/km)"
        df_cat = df_press.dropna(subset=["category"]).copy()

        if not df_cat.empty:
            chunk_size = 10
            q_cat_vals = sorted(df_cat["Q_target (m\u00b3/s)"].unique())
            q_chunks = [q_cat_vals[i:i + chunk_size] for i in range(0, len(q_cat_vals), chunk_size)]

            for cidx, qchunk in enumerate(q_chunks):
                if cancel_flag and cancel_flag():
                    result.logs.append("用户取消（绘图）")
                    return result

                q_start = f"{qchunk[0]:g}"
                q_end = f"{qchunk[-1]:g}"

                df_chunk = df_cat[df_cat["Q_target (m\u00b3/s)"].isin(qchunk)].copy()
                if df_chunk.empty:
                    continue

                nq = len(qchunk)
                ncol = min(5, nq)
                nrow = (nq + ncol - 1) // ncol
                fig = Figure(figsize=(ncol * 7, nrow * 5.5))
                FigureCanvasAgg(fig)
                axes = fig.subplots(nrow, ncol, squeeze=False)

                color_v = "#1976D2"
                color_hf = "darkorange"

                for qi, q_val in enumerate(qchunk):
                    r, c = divmod(qi, ncol)
                    ax1 = axes[r][c]
                    ax2 = ax1.twinx()

                    q_data = df_chunk[df_chunk["Q_target (m\u00b3/s)"] == q_val]
                    if q_data.empty:
                        ax1.text(0.5, 0.5, "无数据", ha="center", va="center", transform=ax1.transAxes)
                        continue

                    for _, row in q_data.iterrows():
                        is_eco = "经济" in row["category"]
                        fc_v = color_v if is_eco else "none"
                        fc_h = color_hf if is_eco else "none"
                        lw = 0.6 if is_eco else 1.8
                        ax1.scatter(row["D (m)"], row["V_press (m/s)"], marker="o", s=70,
                                    facecolors=fc_v, edgecolors=color_v, linewidths=lw, alpha=0.85, zorder=5)
                        ax1.text(row["D (m)"] + 0.015, row["V_press (m/s)"],
                                 f" {row['V_press (m/s)']:.2f}", fontsize=6.5, color=color_v, fontweight="bold", va="center")
                        ax2.scatter(row["D (m)"], row["hf_total_press (m/km)"], marker="o", s=70,
                                    facecolors=fc_h, edgecolors=color_hf, linewidths=lw, alpha=0.85, zorder=5)
                        ax2.text(row["D (m)"] - 0.015, row["hf_total_press (m/km)"],
                                 f" {row['hf_total_press (m/km)']:.2f} ", fontsize=6.5, color=color_hf, fontstyle="italic", va="center", ha="right")

                    ax1.set_ylim(0.5, 1.8)
                    ax2.set_ylim(0, 5.5)
                    ax1.set_xlabel("水力计算内径 (m)")
                    ax1.set_ylabel("流速 V (m/s)", color=color_v)
                    ax2.set_ylabel("总水头损失 (m/km)", color=color_hf)
                    ax1.tick_params(axis="y", labelcolor=color_v)
                    ax2.tick_params(axis="y", labelcolor=color_hf)
                    ax1.set_title(f"Q = {q_val:g} {PLOT_FLOW_UNIT_M3_PER_S}")
                    _setup_adaptive_xaxis(ax1, q_data["D (m)"].tolist())

                # 隐藏多余子图
                for qi in range(nq, nrow * ncol):
                    r, c = divmod(qi, ncol)
                    axes[r][c].set_visible(False)

                fig.suptitle(
                    f"有压管道优选设计点 "
                    f"(Q: {q_start}-{q_end} {PLOT_FLOW_UNIT_M3_PER_S}, {mat_name})",
                    fontsize=14,
                )
                fig.tight_layout(rect=[0, 0, 1, 0.95])

                pdf_name = f"图2_优选设计点_{q_start}_{q_end}_{safe_mat}.pdf"
                pdf_path = os.path.join(output_dir, pdf_name)
                if config.output_pdf_charts:
                    actual2 = _safe_savefig(fig, pdf_path, dpi=150)
                    result.generated_pdfs.append(actual2)
                    result.logs.append(f"PDF: {os.path.basename(actual2)}")

                _chart_count += 1
                if progress_cb:
                    progress_cb(
                        _PHASE1_END + int(_chart_count / _chart_total * ((900 if _has_unpr else _PHASE2_END) - _PHASE1_END)),
                        _TOTAL_STEPS,
                        f"绘图中 ({_chart_count}/{_chart_total}) {pdf_name}",
                    )

                # 子图 PNG - 为每个Q值创建独立完整的figure
                if config.output_subplot_png:
                    png_dir = os.path.join(output_dir, "子图PNG", safe_mat)
                    os.makedirs(png_dir, exist_ok=True)
                    for qi, q_val in enumerate(qchunk):
                        # 筛选当前Q值的数据
                        q_data_sub = df_chunk[df_chunk["Q_target (m\u00b3/s)"] == q_val]
                        if q_data_sub.empty:
                            continue

                        # 创建独立figure
                        fig_sub2 = Figure(figsize=(10, 7))
                        FigureCanvasAgg(fig_sub2)
                        ax_sub2 = fig_sub2.add_subplot(111)
                        ax_sub2_twin = ax_sub2.twinx()

                        ax_sub2.set_xlabel("水力计算内径 (m)", fontsize=12)

                        # 绘制散点
                        color_v_sub2 = "#1976D2"
                        color_hf_sub2 = "darkorange"

                        for _, row in q_data_sub.iterrows():
                            is_eco = "经济" in row["category"]
                            fc_v = color_v_sub2 if is_eco else "none"
                            fc_h = color_hf_sub2 if is_eco else "none"
                            lw = 0.6 if is_eco else 1.8

                            # 流速散点（左Y轴）
                            ax_sub2.scatter(row["D (m)"], row["V_press (m/s)"], marker="o", s=80,
                                           facecolors=fc_v, edgecolors=color_v_sub2, linewidths=lw, alpha=0.85, zorder=5)
                            ax_sub2.text(row["D (m)"] + 0.02, row["V_press (m/s)"],
                                        f" {row['V_press (m/s)']:.2f}m/s", fontsize=8, color=color_v_sub2,
                                        fontweight="bold", va="center")

                            # 水头损失散点（右Y轴）
                            ax_sub2_twin.scatter(row["D (m)"], row["hf_total_press (m/km)"], marker="o", s=80,
                                                facecolors=fc_h, edgecolors=color_hf_sub2, linewidths=lw, alpha=0.85, zorder=5)
                            ax_sub2_twin.text(row["D (m)"] - 0.02, row["hf_total_press (m/km)"],
                                             f" {row['hf_total_press (m/km)']:.2f}m/km ", fontsize=8, color=color_hf_sub2,
                                             fontstyle="italic", va="center", ha="right")

                        # 设置左Y轴
                        ax_sub2.set_ylim(0.5, 1.8)
                        ax_sub2.set_ylabel("流速 V (m/s)", fontsize=12, color=color_v_sub2)
                        ax_sub2.tick_params(axis="y", labelcolor=color_v_sub2)
                        ax_sub2.spines["left"].set_edgecolor(color_v_sub2)
                        ax_sub2.spines["left"].set_linewidth(1.5)

                        # 设置右Y轴
                        ax_sub2_twin.set_ylim(0, 5.5)
                        ax_sub2_twin.set_ylabel("总水头损失 (m/km)", fontsize=11, color=color_hf_sub2)
                        ax_sub2_twin.tick_params(axis="y", labelcolor=color_hf_sub2)
                        ax_sub2_twin.spines["right"].set_edgecolor(color_hf_sub2)
                        ax_sub2_twin.spines["right"].set_linewidth(1.5)

                        # 自适应X轴
                        _setup_adaptive_xaxis(ax_sub2, q_data_sub["D (m)"].tolist(), fontsize=10)

                        # 设置标题
                        fig_sub2.suptitle(
                            f"图2: 有压管道优选设计点\n"
                            f"目标流量 Q = {q_val:g} {PLOT_FLOW_UNIT_M3_PER_S}, 管材: {mat_name}",
                            fontsize=14,
                            y=0.98,
                        )

                        # 创建图例
                        handles_sub2 = [
                            Line2D([0], [0], marker="o", color="w",
                                  markerfacecolor=color_v_sub2, markeredgecolor=color_v_sub2,
                                  markersize=8, linestyle="None", mew=0.6, label="经济区 流速 (实心蓝)"),
                            Line2D([0], [0], marker="o", color="w",
                                  markerfacecolor=color_hf_sub2, markeredgecolor=color_hf_sub2,
                                  markersize=8, linestyle="None", mew=0.6, label="经济区 总水损 (实心橙)"),
                            Line2D([0], [0], marker="o", color="w",
                                  markerfacecolor="none", markeredgecolor=color_v_sub2,
                                  markersize=8, linestyle="None", mew=1.8, label="妥协区 流速 (空心蓝)"),
                            Line2D([0], [0], marker="o", color="w",
                                  markerfacecolor="none", markeredgecolor=color_hf_sub2,
                                  markersize=8, linestyle="None", mew=1.8, label="妥协区 总水损 (空心橙)")
                        ]
                        fig_sub2.legend(handles=handles_sub2, loc='upper right',
                                       bbox_to_anchor=(0.98, 0.88), fontsize=9, frameon=True, ncol=2)

                        # 保存
                        fig_sub2.tight_layout(rect=[0, 0, 1, 0.93])
                        png_name = f"图2_Q{q_val:g}_{safe_mat}.png"
                        png_path = os.path.join(png_dir, png_name)
                        actual_png2 = _safe_savefig(fig_sub2, png_path, dpi=300, bbox_inches='tight', pad_inches=0.1)
                        result.generated_pngs.append(actual_png2)
                        plt.close(fig_sub2)

                plt.close(fig)

    if _has_unpr:
        from calc_渠系计算算法内核.unpressurized_plots import export_comparison_charts
        if not export_comparison_charts(result.comparison_rows, config, result, _safe_savefig, progress_cb, cancel_flag):
            return result

    # ---- 阶段3: 合并 PDF ----
    if progress_cb:
        progress_cb(_PHASE2_END, _TOTAL_STEPS, "合并PDF文件...")
    if config.output_merged_pdf and result.generated_pdfs:
        try:
            from pypdf import PdfWriter
            merger = PdfWriter()
            for p in sorted(result.generated_pdfs):
                merger.append(p)
            merged_name = "合并图表_有压管道批量计算.pdf"
            merged_path = os.path.join(output_dir, merged_name)
            with open(merged_path, "wb") as fout:
                merger.write(fout)
            merger.close()
            result.merged_pdf = merged_path
            result.logs.append(f"合并PDF: {merged_path}")
        except ImportError:
            result.logs.append("警告: pypdf 未安装，跳过PDF合并")
        except Exception as e:
            result.logs.append(f"合并PDF失败: {e}")
    elif not config.output_merged_pdf:
        result.logs.append("已跳过 合并PDF 输出（配置为关闭）")

    if progress_cb:
        progress_cb(_TOTAL_STEPS, _TOTAL_STEPS, "批量计算完成")

    return result


# ============================================================
# 5. 内部辅助
# ============================================================

def _build_process_text(
    inp: PressurePipeInput,
    all_candidates: List[DiameterCandidate],
    recommended: DiameterCandidate,
    category: str,
    *,
    auto_rec: Optional[DiameterCandidate] = None,
    auto_cat: Optional[str] = None,
) -> str:
    """生成完整计算过程文本（供公式渲染器使用）

    格式约定与其他模块（渡槽/隧洞/暗涵）保持一致：
      - "=" * 70 作为主分隔线
      - 标题行包含 "计算结果"，被渲染器识别为居中标题
      - 【...】 作为章节横幅
      - "  N. 标签:" + 缩进内容 作为编号步骤卡片

    当 category=="指定" 时:
      - auto_rec / auto_cat 为自动推荐结果，用于对比展示
    """
    mat = PIPE_MATERIALS[inp.material_key]
    mat_name = mat.get("display_name", mat["name"])
    is_manual = (category == "指定")
    is_pe = (
        recommended.product_family == "PE"
        or recommended.pe_material_grade is not None
    )
    has_generic_product = recommended.product_family in {"DI", "PCCP", "FRPM"}
    legacy_migration_flags = [
        flag for flag in recommended.flags
        if flag.startswith("旧版水力内径")
    ]
    f_lower = mat.get("f_min")
    has_f_range = (
        f_lower is not None
        and recommended.hf_friction_lower_km is not None
        and float(f_lower) < float(mat["f"])
    )

    o = []
    o.append("=" * 70)
    o.append("              有压管道水力计算结果")
    o.append("=" * 70)
    o.append("")

    # ---- 一、输入参数 ----
    o.append("【一、输入参数】")
    o.append("")
    _n = 1
    o.append(f"  {_n}. 设计流量:")
    o.append(f"     Q = {inp.Q} m\u00b3/s")
    o.append("")
    _n += 1
    o.append(f"  {_n}. 管材类型:")
    o.append(f"     {mat_name}")
    o.append("")
    if is_pe:
        _n += 1
        o.append(f"  {_n}. PE 产品系列:")
        o.append(
            f"     {recommended.pe_material_grade}，PN {recommended.pe_nominal_pressure_mpa:g} MPa，"
            f"SDR {recommended.pe_sdr:g}（20℃、总体使用系数 C=1.25）"
        )
        o.append(f"     产品尺寸依据: {recommended.product_standard} 表2、表3")
        o.append("")
    elif has_generic_product:
        _n += 1
        o.append(f"  {_n}. 产品规格目录:")
        o.append(f"     {_format_candidate_size(recommended)}")
        if recommended.product_standard_references:
            o.append(
                "     工程/产品依据: "
                + "、".join(recommended.product_standard_references)
            )
        if recommended.product_source_locator:
            o.append(f"     规格表定位: {recommended.product_source_locator}")
        if recommended.product_family == "PCCP":
            o.append("     PCCP 产品型式与本次所选摩阻参数预设相互独立。")
            o.append("     本结果仅完成规格选径和水力计算，不代替结构、承压与覆土荷载验算。")
        elif recommended.product_family == "FRPM":
            o.append("     自动选径仅采用内径系列；端部实际内径应在施工图阶段按供货资料复核。")
        elif recommended.product_family == "DI":
            o.append("     水力内径为按 DE、表列公称壁厚及水泥砂浆内衬厚度换算的名义值。")
        o.append("")
    _n += 1
    o.append(f"  {_n}. 管材系数:")
    if has_f_range:
        o.append(
            f"     f = {float(f_lower):.0f}～{float(mat['f']):.0f}，"
            f"m = {mat['m']}，b = {mat['b']}（上下限均计算）"
        )
    else:
        o.append(f"     f = {mat['f']}, m = {mat['m']}, b = {mat['b']}")
    o.append("")
    _n += 1
    o.append(f"  {_n}. 管长:")
    o.append(f"     L = {inp.length_m} m")
    o.append("")
    if is_manual and is_pe:
        _n += 1
        o.append(f"  {_n}. 指定 PE 公称外径:")
        o.append(f"     DN = {recommended.nominal_outer_diameter_mm} mm（规范离散规格）")
        if legacy_migration_flags:
            o.append(f"     旧项目迁移: {legacy_migration_flags[0]}")
        o.append("")
    elif is_manual and has_generic_product:
        _n += 1
        o.append(f"  {_n}. 指定产品公称口径:")
        o.append(
            f"     {recommended.nominal_symbol} = {recommended.nominal_diameter_mm:g} mm"
            "（规范离散规格）"
        )
        if legacy_migration_flags:
            o.append(f"     旧项目迁移: {legacy_migration_flags[0]}")
        o.append("")
    elif is_manual and inp.manual_D is not None:
        _n += 1
        o.append(f"  {_n}. 指定管径:")
        o.append(f"     D = {inp.manual_D} m ({inp.manual_D * 1000:.0f} mm)")
        o.append("")
    _n += 1
    if inp.manual_increase_percent is not None:
        o.append(f"  {_n}. 加大流量比例:")
        o.append(f"     {inp.manual_increase_percent:.3f}% (手动指定)")
    else:
        pct = get_flow_increase_percent(inp.Q)
        o.append(f"  {_n}. 加大流量比例:")
        o.append(f"     {pct:.3f}% (自动计算)")
    o.append("")

    # ---- 二、加大流量计算 ----
    pct = recommended.increase_pct
    Q_inc = recommended.Q_increased
    Q_inc_m3h = Q_inc * 3600.0

    o.append("【二、加大流量计算】")
    o.append("")
    o.append("  1. 加大流量计算:")
    o.append(f"     加大百分比 P = {pct:.3f}%")
    o.append(f"     Q加大 = Q × (1 + {pct / 100.0:.5f})")
    o.append(f"          = {inp.Q:.3f} × {1 + pct / 100.0:.5f}")
    o.append(f"          = {Q_inc:.3f} m\u00b3/s")
    o.append("")
    o.append("  2. 流量单位换算:")
    o.append(f"     Q' = Q加大 × 3600")
    o.append(f"        = {Q_inc:.3f} × 3600")
    o.append(f"        = {Q_inc_m3h:.2f} m\u00b3/h")
    o.append("")

    # ---- 三、管径计算 ----
    D = recommended.D
    d_mm = D * 1000
    d_mm_text = f"{d_mm:g}" if recommended.product_family == "STEEL" else f"{d_mm:.1f}" if is_pe or recommended.product_family == "DI" else f"{d_mm:.0f}"
    A_full = math.pi * D ** 2 / 4.0

    section3_title = "【三、指定管径计算】" if is_manual else "【三、推荐管径计算】"
    o.append(section3_title)
    o.append("")
    step3_label = "指定管径:" if is_manual else "推荐管径:"
    o.append(f"  1. {step3_label}")
    if recommended.product_family == "STEEL":
        o.append(f"     钢管预选尺寸: {_format_candidate_size(recommended)}")
        o.extend(f"     {line}" for line in steel_sizing_process(recommended.steel_sizing_trace))
        o.extend(f"     {line}" for line in steel_dimension_process(recommended))
    elif is_pe:
        o.append(
            f"     造价/采购规格: {recommended.pe_material_grade} 给水管，"
            f"DN{recommended.nominal_outer_diameter_mm}×{recommended.nominal_wall_thickness_mm:g} mm，"
            f"SDR{recommended.pe_sdr:g}，PN{recommended.pe_nominal_pressure_mpa:g} MPa，"
            f"{recommended.product_standard}"
        )
        o.append("     水力计算采用名义内径:")
        o.append(
            f"     di = DN - 2en = {recommended.nominal_outer_diameter_mm} - "
            f"2×{recommended.nominal_wall_thickness_mm:g} = "
            f"{recommended.hydraulic_inner_diameter_mm:g} mm = {D:g} m"
        )
    elif recommended.product_family == "DI":
        o.append(
            f"     造价/采购规格: 球墨铸铁管 DN{recommended.nominal_diameter_mm:g}，"
            f"{recommended.class_code}，DE{recommended.outer_diameter_mm:g}×"
            f"e{recommended.nominal_wall_thickness_mm:g} mm，"
            f"水泥砂浆内衬 {recommended.lining_thickness_mm:g} mm"
        )
        o.append("     水力计算采用名义换算内径:")
        o.append(
            f"     di = DE - 2(e_nom + e_c) = {recommended.outer_diameter_mm:g} - "
            f"2×({recommended.nominal_wall_thickness_mm:g} + "
            f"{recommended.lining_thickness_mm:g}) = "
            f"{recommended.hydraulic_inner_diameter_mm:g} mm = {D:g} m"
        )
    elif recommended.product_family == "PCCP":
        o.append(
            f"     造价/采购规格: {recommended.product_variant}，"
            f"DN={recommended.nominal_diameter_mm:g} mm"
        )
        o.append(
            f"     水力计算采用产品公称内径 DN={recommended.hydraulic_inner_diameter_mm:g} mm"
        )
    elif recommended.product_family == "FRPM":
        o.append(
            f"     造价/采购规格: 玻璃钢夹砂管内径系列 DN"
            f"{recommended.nominal_diameter_mm:g}"
        )
        o.append(
            f"     名义水力内径 di={recommended.hydraulic_inner_diameter_mm:g} mm；"
            f"两端内径允许范围 {recommended.minimum_inner_diameter_mm:g}～"
            f"{recommended.maximum_inner_diameter_mm:g} mm，"
            f"相对所选设计值允许偏差 ±{recommended.selected_inner_diameter_tolerance_mm:g} mm"
        )
    else:
        o.append(f"     D = {D} m ({d_mm:.0f} mm)")
    o.append("")
    o.append("  2. 过水面积计算:")
    diameter_symbol = "di" if is_pe or has_generic_product else "D"
    o.append(f"     A = π × {diameter_symbol}² / 4")
    o.append(f"       = π × {D}² / 4")
    o.append(f"       = {A_full:.6f} m²")
    o.append("")
    o.append("  3. 有压流速计算:")
    o.append(f"     V = Q / A")
    o.append(f"       = {inp.Q} / {A_full:.6f}")
    o.append(f"       = {recommended.V_press:.4f} m/s")
    o.append("")
    o.append("  4. 沿程水头损失计算:")
    o.append("     hf = f × (1000 × (Q')^{m}) / (d^{b})")
    if has_f_range:
        o.append(f"     f 取上限 {float(mat['f']):.0f}:")
        o.append(
            f"        = {mat['f']} × (1000 × ({Q_inc_m3h:.2f})^{{{mat['m']}}}) "
            f"/ (({d_mm_text})^{{{mat['b']}}})"
        )
        o.append(f"        = {recommended.hf_friction_km:.4f} m/km")
        o.append(f"     f 取下限 {float(f_lower):.0f}:")
        o.append(
            f"        = {float(f_lower):.0f} × (1000 × ({Q_inc_m3h:.2f})^{{{mat['m']}}}) "
            f"/ (({d_mm_text})^{{{mat['b']}}})"
        )
        o.append(f"        = {recommended.hf_friction_lower_km:.4f} m/km")
    else:
        o.append(
            f"        = {mat['f']} × (1000 × ({Q_inc_m3h:.2f})^{{{mat['m']}}}) "
            f"/ (({d_mm_text})^{{{mat['b']}}})"
        )
        o.append(f"        = {recommended.hf_friction_km:.4f} m/km")
    o.append("")
    o.append("  5. 局部水头损失计算:")
    _ratio = inp.local_loss_ratio
    if has_f_range:
        o.append(f"     f 上限: hj = {_ratio} × {recommended.hf_friction_km:.4f}")
        o.append(f"                  = {recommended.hf_local_km:.4f} m/km")
        o.append(f"     f 下限: hj = {_ratio} × {recommended.hf_friction_lower_km:.4f}")
        o.append(f"                  = {recommended.hf_local_lower_km:.4f} m/km")
    else:
        o.append(f"     hj = {_ratio} × hf")
        o.append(f"         = {_ratio} × {recommended.hf_friction_km:.4f}")
        o.append(f"         = {recommended.hf_local_km:.4f} m/km")
    o.append("")
    o.append("  6. 总水头损失计算:")
    if has_f_range:
        o.append(
            f"     f 上限: hf总 = {recommended.hf_friction_km:.4f} "
            f"+ {recommended.hf_local_km:.4f} = {recommended.hf_total_km:.4f} m/km"
        )
        o.append(
            f"     f 下限: hf总 = {recommended.hf_friction_lower_km:.4f} "
            f"+ {recommended.hf_local_lower_km:.4f} = {recommended.hf_total_lower_km:.4f} m/km"
        )
    else:
        o.append("     hf总 = hf + hj")
        o.append(f"         = {recommended.hf_friction_km:.4f} + {recommended.hf_local_km:.4f}")
        o.append(f"         = {recommended.hf_total_km:.4f} m/km")
    o.append("")
    o.append("  7. 按管长折算总损失:")
    if has_f_range:
        o.append(
            f"     f 上限: H损 = {recommended.hf_total_km:.4f} × "
            f"({inp.length_m} / 1000) = {recommended.h_loss_total_m:.4f} m"
        )
        o.append(
            f"     f 下限: H损 = {recommended.hf_total_lower_km:.4f} × "
            f"({inp.length_m} / 1000) = {recommended.h_loss_total_lower_m:.4f} m"
        )
        o.append("     说明: 推荐与类别判定仍按 f 上限结果，两个区间结果均列出供设计选用。")
    else:
        o.append("     H损 = hf总 × (L / 1000)")
        o.append(f"        = {recommended.hf_total_km:.4f} × ({inp.length_m} / 1000)")
        o.append(f"        = {recommended.h_loss_total_m:.4f} m")
    o.append("")

    # ---- 四、筛选判定 ----
    eco_count = sum(1 for c in all_candidates if c.category == "经济")
    comp_count = sum(1 for c in all_candidates if c.category == "妥协")
    fallback_count = sum(1 for c in all_candidates if c.category == "兜底")

    o.append("【四、筛选判定】")
    o.append("")
    o.append("  1. 经济区条件:")
    o.append("     0.9 ≤ V ≤ 1.5 m/s 且 hf总 ≤ 5.0 m/km")
    o.append("")
    o.append("  2. 妥协区条件:")
    o.append("     0.6 ≤ V < 0.9 m/s 且 hf总 ≤ 5.0 m/km")
    o.append("")
    o.append("  3. 双规范说明:")
    o.append("     规范依据并列展示：GB 50288-2018 与 GB/T 20203-2017")
    o.append("     当前程序筛选规则仍按 GB 50288-2018 执行")
    if is_pe:
        o.append("     PE 的 DN、en、SDR、PN 取自 GB/T 13663.2-2018；水力公式仅代入 di")
        o.append("     PN 为20℃、C=1.25条件值；工作温度、设计内水压力及水击仍应另行复核")
    o.append("")
    o.append(f"  4. 评价统计:")
    o.append(f"     全部 {len(all_candidates)} 种口径: 经济区 {eco_count} 个, 妥协区 {comp_count} 个, 兜底 {fallback_count} 个")
    o.append("")
    o.append(f"  5. 筛选结论:")
    if is_manual:
        o.append(f"     用户指定规格: {_format_candidate_size(recommended)}")
        o.append(f"     该管径属于「{recommended.category}」区")
        if auto_rec is not None and auto_cat:
            o.append(f"     自动推荐({auto_cat}区): {_format_candidate_size(auto_rec)}")
    elif category == "经济":
        o.append(f"     存在经济区口径，取最小合规规格: {_format_candidate_size(recommended)}")
    elif category == "妥协":
        o.append(f"     无经济区口径，妥协区取最小合规规格: {_format_candidate_size(recommended)}")
    else:
        if recommended.steel_sizing_trace:
            o.append(f"     整百外径上取后未满足流速下限，仅作参考: {_format_candidate_size(recommended)}")
        else:
            o.append(f"     无经济区/妥协区口径，按 |V-0.9| 最小兜底选取: {_format_candidate_size(recommended)}")
        o.append(f"     注意: 未满足经济/妥协约束条件!")
    o.append("")

    # ---- 五、结果汇总 ----
    section5_label = "指定管径" if is_manual else "推荐管径"
    o.append(f"【五、{section5_label}结果】")
    # 最终结果优先给出用户选管所需的公称规格，实际水力内径另列，不能取整冒充DN。
    if is_pe or has_generic_product or recommended.product_family == 'STEEL':
        nominal_mm = recommended.nominal_outer_diameter_mm if is_pe else recommended.nominal_diameter_mm
        o.append(f"  1. {section5_label} DN {nominal_mm:g}")
    if is_pe:
        o.append(f"  造价/采购规格: {_format_candidate_size(recommended)}")
        o.append(f"  公称外径: {recommended.nominal_outer_diameter_mm:g} mm")
        o.append(f"  单侧管壁厚: {recommended.nominal_wall_thickness_mm:g} mm")
        o.append(f"  产品标准: {recommended.product_standard}")
        if recommended.nominal_outer_diameter_mm > 400:
            o.append("  工程提示: DN>400 mm 时，GB/T 20203-2017 建议结合其他管材进行技术经济比较。")
        o.append("  尺寸边界: di 为按公称尺寸计算的名义内径；制造公差或最小过流面积应另据产品资料复核。")
    elif recommended.product_family == 'STEEL':
        o.append(f"  公称外径: {recommended.outer_diameter_mm:g} mm")
        o.append(f"  构造最小壁厚（单侧）: {recommended.nominal_wall_thickness_mm:g} mm")
        o.append(f"  单侧内衬厚: {recommended.lining_thickness_mm:g} mm")
    elif has_generic_product:
        o.append(f"  管材: {mat_name}")
        if recommended.product_family == 'DI':
            o.append(f"  管壁等级: {recommended.class_code}")
            o.append(f"  插口外径: DE = {recommended.outer_diameter_mm:g} mm")
            o.append(f"  单侧管壁厚: {recommended.nominal_wall_thickness_mm:g} mm")
            o.append(f"  单侧内衬厚: {recommended.lining_thickness_mm:g} mm")
        else:
            o.append(f"  公称内径: {recommended.nominal_diameter_mm:g} mm")
            if recommended.product_family == 'PCCP':
                o.append(f"  产品型式: {recommended.product_variant}")
    else:
        o.append(f"  {section5_label}（水力内径）: D = {recommended.D:g} m ({recommended.D * 1000:g} mm)")
    if is_pe or has_generic_product or recommended.product_family == 'STEEL':
        o.append("  水力计算内径:")
        o.append(f"     d_i = {recommended.hydraulic_inner_diameter_mm:g} mm = {recommended.D:g} m")
    o.append(f"  有压流速: V = {recommended.V_press:.4f} m/s")
    if has_f_range:
        o.append(f"  f 上限 {float(mat['f']):.0f}:")
        o.append(f"    沿程水损: hf = {recommended.hf_friction_km:.4f} m/km")
        o.append(f"    局部水损: hj = {recommended.hf_local_km:.4f} m/km")
        o.append(f"    总水损: hf总 = {recommended.hf_total_km:.4f} m/km")
        o.append(f"    按管长折算总损失: H损 = {recommended.h_loss_total_m:.4f} m")
        o.append(f"  f 下限 {float(f_lower):.0f}:")
        o.append(f"    沿程水损: hf = {recommended.hf_friction_lower_km:.4f} m/km")
        o.append(f"    局部水损: hj = {recommended.hf_local_lower_km:.4f} m/km")
        o.append(f"    总水损: hf总 = {recommended.hf_total_lower_km:.4f} m/km")
        o.append(f"    按管长折算总损失: H损 = {recommended.h_loss_total_lower_m:.4f} m")
    else:
        o.append(f"  沿程水损: hf = {recommended.hf_friction_km:.4f} m/km")
        o.append(f"  局部水损: hj = {recommended.hf_local_km:.4f} m/km")
        o.append(f"  总水损: hf总 = {recommended.hf_total_km:.4f} m/km")
        o.append(f"  按管长折算总损失: H损 = {recommended.h_loss_total_m:.4f} m (L={inp.length_m}m)")
    o.append(f"  所属类别: {'指定' if is_manual else recommended.category}")
    if recommended.flags:
        o.append(f"  标记: {', '.join(recommended.flags)}")
    o.append("")

    # ---- 指定模式：自动推荐对比（仅当自动推荐与指定D不同时） ----
    if is_manual and auto_rec is not None and auto_cat and abs(auto_rec.D - recommended.D) > 1e-6:
        o.append("【六、自动推荐对比】")
        o.append(f"  自动推荐规格: {_format_candidate_size(auto_rec)}")
        o.append(f"  有压流速: V = {auto_rec.V_press:.4f} m/s")
        o.append(f"  总水损: hf总 = {auto_rec.hf_total_km:.4f} m/km")
        o.append(f"  按管长折算总损失: H损 = {auto_rec.h_loss_total_m:.4f} m")
        o.append(f"  推荐类别: {auto_cat}")
        o.append("")

    return "\n".join(o)
