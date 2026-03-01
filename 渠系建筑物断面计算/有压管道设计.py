# -*- coding: utf-8 -*-
"""
有压管道设计计算内核

提供：管材参数、口径序列、加大流量、单管径评价、推荐算法、批量扫描、详细过程文本。
所有函数均为纯函数，无全局副作用，供面板和测试调用。
"""

import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Callable

import numpy as np
import pandas as pd
from scipy.optimize import fsolve

# ============================================================
# 1. 常量与配置
# ============================================================

PIPE_MATERIALS = {
    "HDPE管":           {"f": 0.948e5, "m": 1.77, "b": 4.77, "name": "HDPE管"},
    "玻璃钢夹砂管":     {"f": 0.948e5, "m": 1.77, "b": 4.77, "name": "玻璃钢夹砂管"},
    "球墨铸铁管":       {"f": 1.899e5, "m": 1.852, "b": 4.87, "name": "球墨铸铁管"},
    "预应力钢筒混凝土管": {"f": 1.312e6, "m": 2.0,  "b": 5.33, "name": "预应力钢筒混凝土管(n=0.013)"},
    "预应力钢筒混凝土管_n014": {"f": 1.516e6, "m": 2.0, "b": 5.33, "name": "预应力钢筒混凝土管(n=0.014)"},
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
DEFAULT_SLOPE_DENOMINATORS = [500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000]
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
    diameter_values: np.ndarray
    materials: List[str]           # 管材键名列表
    n_unpr: float = 0.014
    length_m: float = 1000.0
    local_loss_ratio: float = 0.15  # 局部损失比例
    output_dir: str = ""
    # ===== 输出选项 (可按需开启/关闭) =====
    output_csv: bool = True           # CSV计算结果：包含所有工况的原始数据，便于后续分析
    output_pdf_charts: bool = True    # 图表PDF(图1+图2)：流速对比图和优选设计点图
    output_merged_pdf: bool = True    # 合并PDF：将所有图表合并成一个完整文档
    output_subplot_png: bool = True   # 子图PNG：每个Q值生成独立的高清PNG图片(300DPI)


@dataclass
class BatchScanResult:
    """批量扫描结果"""
    csv_path: str = ""
    generated_pngs: List[str] = field(default_factory=list)
    generated_pdfs: List[str] = field(default_factory=list)
    merged_pdf: str = ""
    logs: List[str] = field(default_factory=list)


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
    """
    求解圆管无压均匀流 Manning 方程 (与 V9 一致)。

    返回 (y, v, y_D, Q_full, Q_max, clr_h, clr_a_pct, flag_clr_h, flag_clr_a, notes)
    所有失败情况返回 NaN + 备注字符串。
    """
    nan = float('nan')
    notes = []

    A_full = math.pi * D ** 2 / 4.0
    R_full = D / 4.0
    Q_full = (1.0 / n) * A_full * (R_full ** (2.0 / 3.0)) * (i ** 0.5)
    Q_max = _calc_q_max_unpressurized(D, n, i)

    y, v, y_D = nan, nan, nan
    clr_h, clr_a_pct = nan, nan
    flag_clr_h, flag_clr_a = False, False

    if Q > Q_max * 1.001:
        notes.append(f"Q>{Q_max:.4f}(Q_max_unpr)")
        return y, v, y_D, Q_full, Q_max, clr_h, clr_a_pct, flag_clr_h, flag_clr_a, "; ".join(notes)

    def manning_eq(y_arr):
        yt = y_arr[0]
        if yt <= 1e-7:
            return -Q
        y_eff = min(max(yt, 1e-7), D)
        if abs(y_eff - D) < 1e-6:
            A_w, P_w = A_full, math.pi * D
        else:
            acos_arg = max(-1.0, min(1.0, 1.0 - 2.0 * y_eff / D))
            theta = 2.0 * math.acos(acos_arg)
            A_w = (D ** 2 / 8.0) * (theta - math.sin(theta))
            P_w = (D / 2.0) * theta
        if A_w < 1e-9 or P_w < 1e-9:
            return -Q
        R_h = max(0.0, A_w / P_w)
        return (1.0 / n) * A_w * (R_h ** (2.0 / 3.0)) * (i ** 0.5) - Q

    y_guess = D * 0.5
    if Q_full > 1e-9 and Q / Q_full > 0.7:
        y_guess = D * 0.85

    try:
        y_sol, _, ier, msg = fsolve(manning_eq, [y_guess], full_output=True, xtol=1e-7)
        if ier != 1 and Q >= 0.98 * Q_full and Q <= Q_max * 1.001:
            for alt_guess in [D * 0.938, D * 0.99]:
                y_alt, _, ier_alt, _ = fsolve(manning_eq, [alt_guess], full_output=True, xtol=1e-7)
                if ier_alt == 1:
                    y_sol, ier = y_alt, ier_alt
                    break

        if ier == 1:
            y = min(D, max(0.0, y_sol[0]))
            if abs(y - D) < 1e-5:
                A_w, R_h = A_full, R_full
            elif y <= 1e-6:
                A_w, R_h = 0.0, 0.0
            else:
                acos_arg = max(-1.0, min(1.0, 1.0 - 2.0 * y / D))
                theta = 2.0 * math.acos(acos_arg)
                A_w = (D ** 2 / 8.0) * (theta - math.sin(theta))
                P_w = (D / 2.0) * theta
                R_h = A_w / P_w if P_w > 1e-9 else 0.0

            y_D = y / D if D > 0 else 0.0
            v = Q / A_w if A_w > 1e-9 else nan

            clr_h = D - y
            if A_full > 1e-9:
                clr_a_abs = max(0.0, A_full - A_w)
                clr_a_pct = (clr_a_abs / A_full) * 100.0
            if not math.isnan(clr_h) and clr_h < 0.4:
                flag_clr_h = True
            if not math.isnan(clr_a_pct) and clr_a_pct < 15.0:
                flag_clr_a = True
        else:
            notes.append(f"求解失败:{msg[:30]}")
    except Exception as e:
        notes.append(f"求解异常:{str(e)[:30]}")

    return y, v, y_D, Q_full, Q_max, clr_h, clr_a_pct, flag_clr_h, flag_clr_a, "; ".join(notes)


def evaluate_single_diameter(inp: PressurePipeInput, D: float) -> DiameterCandidate:
    """
    对给定管径 D 评价有压管道水力性能。

    公式:
        V_press = Q / A_full
        Q_inc = Q * (1 + p/100)
        hf_friction_km = f * (1000 * Q_inc_m3h^m) / (d_mm^b)
        hf_local_km = local_loss_ratio * hf_friction_km
        hf_total_km = hf_friction_km + hf_local_km
        h_total_m = hf_total_km * (L / 1000)
    """
    if D <= 0:
        raise ValueError(f"管径 D 必须大于 0, 当前 D={D}")
    if inp.Q <= 0:
        raise ValueError(f"设计流量 Q 必须大于 0, 当前 Q={inp.Q}")
    if inp.material_key not in PIPE_MATERIALS:
        raise ValueError(f"未知管材: {inp.material_key}")

    mat = PIPE_MATERIALS[inp.material_key]
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
    )


_CAT_ORDER = {"经济": 0, "妥协": 1, "兜底": 2}


def _auto_recommend(candidates):
    """从 candidates 中按经济→妥协→兜底规则选出自动推荐结果，返回 (rec, category)"""
    eco = sorted([c for c in candidates if c.category == "经济"], key=lambda c: c.hf_total_km)
    comp = sorted([c for c in candidates if c.category == "妥协"], key=lambda c: c.hf_total_km)
    if eco:
        return eco[0], "经济"
    if comp:
        return comp[0], "妥协"
    fb = sorted(candidates, key=lambda c: (abs(c.V_press - 0.9), c.hf_total_km))
    if fb:
        return fb[0], "兜底"
    return None, "无可用"


def recommend_diameter(inp: PressurePipeInput) -> RecommendationResult:
    """
    推荐管径算法：
    1. 筛选"经济区"(0.9<=V<=1.5 且 hf_total<=5)，取最小 D
    2. 若无，筛选"妥协区"(0.6<=V<0.9 且 hf_total<=5)，取最小 D
    3. 若仍无，按 |V-0.9| 最小 + hf_total 最小 兜底
    返回前 5 候选（获胜类别优先，不足时从其他类别补足）。

    当 inp.manual_D 不为 None 时：
    - 仍遍历所有标准管径生成候选表
    - 将指定D强制设为推荐结果（若非标准管径则额外加入候选表）
    - auto_recommended 存储自动推荐结果供对比
    """
    candidates = []
    for D in DEFAULT_DIAMETER_SERIES:
        try:
            c = evaluate_single_diameter(inp, float(D))
            candidates.append(c)
        except ValueError:
            continue

    # ---- 用户指定管径模式 ----
    if inp.manual_D is not None and inp.manual_D > 0:
        manual_D_val = inp.manual_D
        # 查找指定D是否已在候选中（浮点容差）
        manual_candidate = None
        for c in candidates:
            if abs(c.D - manual_D_val) < 1e-6:
                manual_candidate = c
                break
        # 若非标准管径，额外评价并加入候选列表
        if manual_candidate is None:
            try:
                manual_candidate = evaluate_single_diameter(inp, manual_D_val)
                manual_candidate.flags.append("非标准管径")
                candidates.append(manual_candidate)
            except ValueError:
                pass
        if manual_candidate is not None:
            fallback_sorted = sorted(candidates, key=lambda c: (abs(c.V_press - 0.9), c.hf_total_km))
            # 自动推荐结果（在追加"用户指定"标记之前调用，避免同对象污染）
            auto_rec, auto_cat = _auto_recommend(candidates)
            manual_candidate.flags.append("用户指定")
            # top: 指定D排首位，其余按原排序补足
            top5 = [manual_candidate]
            seen_D = {manual_candidate.D}
            for c in fallback_sorted:
                if c.D not in seen_D:
                    top5.append(c)
                    seen_D.add(c.D)
                    if len(top5) >= 6:
                        break
            top5 = sorted(top5, key=lambda c: (_CAT_ORDER.get(c.category, 9), c.hf_total_km))
            reason = (f"用户指定: D={manual_candidate.D:.3f}m, "
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
    eco = sorted([c for c in candidates if c.category == "经济"], key=lambda c: c.hf_total_km)
    comp = sorted([c for c in candidates if c.category == "妥协"], key=lambda c: c.hf_total_km)
    fallback_sorted = sorted(candidates, key=lambda c: (abs(c.V_press - 0.9), c.hf_total_km))

    def _fill_top5(primary, all_sorted):
        """获胜类别优先，不足5个时从 all_sorted 补足（去重），结果按 (类别优先级, hf_total) 排列"""
        top = list(primary[:5])
        if len(top) < 5:
            seen_D = {c.D for c in top}
            for c in all_sorted:
                if c.D not in seen_D:
                    top.append(c)
                    seen_D.add(c.D)
                    if len(top) >= 5:
                        break
        return sorted(top, key=lambda c: (_CAT_ORDER.get(c.category, 9), c.hf_total_km))

    # ---- 自动推荐模式（原逻辑） ----

    # 第一步：经济区
    if eco:
        rec = eco[0]
        top5 = _fill_top5(eco, fallback_sorted)
        reason = f"经济优先: D={rec.D:.3f}m, V={rec.V_press:.3f}m/s, hf_total={rec.hf_total_km:.4f}m/km"
        calc_text = _build_process_text(inp, candidates, rec, "经济")
        return RecommendationResult(
            recommended=rec, top_candidates=top5,
            category="经济", reason=reason, calc_steps=calc_text,
        )

    # 第二步：妥协区
    if comp:
        rec = comp[0]
        top5 = _fill_top5(comp, fallback_sorted)
        reason = f"妥协兜底: D={rec.D:.3f}m, V={rec.V_press:.3f}m/s, hf_total={rec.hf_total_km:.4f}m/km"
        calc_text = _build_process_text(inp, candidates, rec, "妥协")
        return RecommendationResult(
            recommended=rec, top_candidates=top5,
            category="妥协", reason=reason, calc_steps=calc_text,
        )

    # 第三步：兜底
    rec = fallback_sorted[0]
    rec.flags.append("未满足约束")
    top5 = sorted(fallback_sorted[:5], key=lambda c: (_CAT_ORDER.get(c.category, 9), c.hf_total_km))
    reason = f"就近流速兜底: D={rec.D:.3f}m, V={rec.V_press:.3f}m/s, hf_total={rec.hf_total_km:.4f}m/km (未满足约束)"
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
    批量扫描：遍历 Q x slope x D x material，生成 CSV + PNG + PDF + 合并 PDF。

    progress_cb(current, total, message): 进度回调
    cancel_flag(): 返回 True 时中止
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import seaborn as sns
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MultipleLocator

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
    total = (len(config.q_values) * len(slope_values)
             * len(config.diameter_values) * len(config.materials))
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

        for Q in config.q_values:
            for si, i_val in enumerate(slope_values):
                for D in config.diameter_values:
                    if cancel_flag and cancel_flag():
                        result.logs.append("用户取消")
                        return result

                    count += 1
                    if progress_cb and count % _update_interval == 0:
                        progress_cb(
                            int(count / total * _PHASE1_END),
                            _TOTAL_STEPS,
                            f"计算中 {mat_name} Q={Q:.1f} ({count}/{total})",
                        )

                    inp = PressurePipeInput(
                        Q=float(Q), material_key=mat_key,
                        slope_i=i_val, n_unpr=config.n_unpr,
                        length_m=config.length_m,
                        local_loss_ratio=config.local_loss_ratio,
                    )
                    try:
                        c = evaluate_single_diameter(inp, float(D))
                    except ValueError:
                        continue

                    results_list.append({
                        "管材类型": mat_name,
                        "Q_target (m\u00b3/s)": float(Q),
                        "n_unpr": config.n_unpr if _has_unpr else "",
                        "i_unpr_str": slope_labels[si],
                        "i_unpr_val": i_val if i_val is not None else "",
                        "D (m)": float(D),
                        "y_unpr (m)": c.y_unpr,
                        "v_unpr (m/s)": c.v_unpr,
                        "y/D_unpr": c.y_D_ratio,
                        "V_press (m/s)": c.V_press,
                        "hf_press (m/km)": c.hf_friction_km,
                        "hf_local_press (m/km)": c.hf_local_km,
                        "hf_total_press (m/km)": c.hf_total_km,
                        "h_loss_total (m)": c.h_loss_total_m,
                        "净空高度 (m)": c.clearance_h,
                        "净空面积 (%)": c.clearance_a_pct,
                        "净空高<0.4m": c.flag_clr_h,
                        "净空面积(%)<15": c.flag_clr_a,
                        "Q_full_unpr (m\u00b3/s)": c.Q_full_unpr,
                        "Q_max_unpr (m\u00b3/s)": c.Q_max_unpr,
                        "加大比例 (%)": c.increase_pct,
                        "分类": c.category,
                        "备注": c.unpr_notes,
                    })

    if progress_cb:
        progress_cb(_PHASE1_END, _TOTAL_STEPS, "计算完成，保存CSV...")

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
        df_mat["Q_target (m\u00b3/s)"] = df_mat["Q_target (m\u00b3/s)"].round(1)

        all_Q = sorted(df_mat["Q_target (m\u00b3/s)"].unique())
        safe_mat = mat_name.replace("(", "_").replace(")", "_").replace("=", "_")

        # -- 图1: 无压/有压流速对比 + 水损双轴 (与 V9 一致) --
        df_unpr_valid = df_mat.dropna(subset=["v_unpr (m/s)"]).copy()
        df_press_valid = df_mat.dropna(subset=["V_press (m/s)", "hf_total_press (m/km)"]).copy()

        if not df_unpr_valid.empty or not df_press_valid.empty:
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

                q_start1 = f"{qchunk1[0]:.1f}"
                q_end1 = f"{qchunk1[-1]:.1f}"

                nq1 = len(qchunk1)
                ncol1 = min(5, nq1)
                nrow1 = (nq1 + ncol1 - 1) // ncol1
                fig1, axes1 = plt.subplots(nrow1, ncol1, figsize=(ncol1 * 7, nrow1 * 5.5), squeeze=False)

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

                    ax1.set_xlabel("管径 D (m)")
                    ax1.set_ylabel("流速 (m/s)")
                    ax1.set_title(f"Q = {q_val1:.1f} m$^3$/s")
                    # 自适应X轴
                    _d_q1 = set(df_unpr_valid[df_unpr_valid["Q_target (m\u00b3/s)"] == q_val1]["D (m)"].tolist())
                    if not q_press_data.empty:
                        _d_q1.update(q_press_data["D (m)"].tolist())
                    _setup_adaptive_xaxis(ax1, list(_d_q1))

                # 隐藏多余子图
                for qi1 in range(nq1, nrow1 * ncol1):
                    r1, c1 = divmod(qi1, ncol1)
                    axes1[r1][c1].set_visible(False)

                fig1.suptitle(f"图1: 无压/有压流速与总水损对比 (Q: {q_start1}-{q_end1} m$^3$/s, {mat_name})", fontsize=14)
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
                        _PHASE1_END + int(_chart_count / _chart_total * (_PHASE2_END - _PHASE1_END)),
                        _TOTAL_STEPS,
                        f"绘图中 ({_chart_count}/{_chart_total}) {pdf_name1}",
                    )

                # 子图 PNG - 为每个Q值创建独立完整的figure
                if config.output_subplot_png:
                    png_dir1 = os.path.join(output_dir, "子图PNG", safe_mat)
                    os.makedirs(png_dir1, exist_ok=True)
                    for qi1, q_val1 in enumerate(qchunk1):
                        # 创建独立figure
                        fig_sub1, ax_sub1 = plt.subplots(figsize=(10, 7))
                        ax_sub1_twin = ax_sub1.twinx()

                        ax_sub1.set_xlabel("管径 D (m)", fontsize=12)

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
                        fig_sub1.suptitle(f"图1: 无压/有压流速与总水损对比\n目标流量 Q = {q_val1:.1f} m³/s, 管材: {mat_name}",
                                         fontsize=14, y=0.98)

                        # 合并图例
                        handles_sub1, labels_sub1 = ax_sub1.get_legend_handles_labels()
                        handles_twin1, labels_twin1 = ax_sub1_twin.get_legend_handles_labels()
                        fig_sub1.legend(handles_sub1 + handles_twin1, labels_sub1 + labels_twin1,
                                       loc='upper right', bbox_to_anchor=(0.98, 0.88),
                                       fontsize=8, frameon=True, ncol=2)

                        # 保存
                        fig_sub1.tight_layout(rect=[0, 0, 1, 0.93])
                        png_name1 = f"图1_Q{q_val1:.1f}_{safe_mat}.png"
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

                q_start = f"{qchunk[0]:.1f}"
                q_end = f"{qchunk[-1]:.1f}"

                df_chunk = df_cat[df_cat["Q_target (m\u00b3/s)"].isin(qchunk)].copy()
                if df_chunk.empty:
                    continue

                nq = len(qchunk)
                ncol = min(5, nq)
                nrow = (nq + ncol - 1) // ncol
                fig, axes = plt.subplots(nrow, ncol, figsize=(ncol * 7, nrow * 5.5), squeeze=False)

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
                    ax1.set_xlabel("管径 D (m)")
                    ax1.set_ylabel("流速 V (m/s)", color=color_v)
                    ax2.set_ylabel("总水头损失 (m/km)", color=color_hf)
                    ax1.tick_params(axis="y", labelcolor=color_v)
                    ax2.tick_params(axis="y", labelcolor=color_hf)
                    ax1.set_title(f"Q = {q_val:.1f} m$^3$/s")
                    _setup_adaptive_xaxis(ax1, q_data["D (m)"].tolist())

                # 隐藏多余子图
                for qi in range(nq, nrow * ncol):
                    r, c = divmod(qi, ncol)
                    axes[r][c].set_visible(False)

                fig.suptitle(f"有压管道优选设计点 (Q: {q_start}-{q_end} m$^3$/s, {mat_name})", fontsize=14)
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
                        _PHASE1_END + int(_chart_count / _chart_total * (_PHASE2_END - _PHASE1_END)),
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
                        fig_sub2, ax_sub2 = plt.subplots(figsize=(10, 7))
                        ax_sub2_twin = ax_sub2.twinx()

                        ax_sub2.set_xlabel("管径 D (m)", fontsize=12)

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
                        fig_sub2.suptitle(f"图2: 有压管道优选设计点\n目标流量 Q = {q_val:.1f} m³/s, 管材: {mat_name}",
                                         fontsize=14, y=0.98)

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
                        png_name = f"图2_Q{q_val:.1f}_{safe_mat}.png"
                        png_path = os.path.join(png_dir, png_name)
                        actual_png2 = _safe_savefig(fig_sub2, png_path, dpi=300, bbox_inches='tight', pad_inches=0.1)
                        result.generated_pngs.append(actual_png2)
                        plt.close(fig_sub2)

                plt.close(fig)

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
    mat_name = mat["name"]
    is_manual = (category == "指定")

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
    _n += 1
    o.append(f"  {_n}. 管材系数:")
    o.append(f"     f = {mat['f']}, m = {mat['m']}, b = {mat['b']}")
    o.append("")
    _n += 1
    o.append(f"  {_n}. 管长:")
    o.append(f"     L = {inp.length_m} m")
    o.append("")
    if is_manual and inp.manual_D is not None:
        _n += 1
        o.append(f"  {_n}. 指定管径:")
        o.append(f"     D = {inp.manual_D} m ({inp.manual_D * 1000:.0f} mm)")
        o.append("")
    _n += 1
    if inp.manual_increase_percent is not None:
        o.append(f"  {_n}. 加大流量比例:")
        o.append(f"     {inp.manual_increase_percent}% (手动指定)")
    else:
        pct = get_flow_increase_percent(inp.Q)
        o.append(f"  {_n}. 加大流量比例:")
        o.append(f"     {pct}% (自动计算)")
    o.append("")

    # ---- 二、加大流量计算 ----
    pct = recommended.increase_pct
    Q_inc = recommended.Q_increased
    Q_inc_m3h = Q_inc * 3600.0

    o.append("【二、加大流量计算】")
    o.append("")
    o.append("  1. 加大流量计算:")
    o.append(f"     加大百分比 P = {pct}%")
    o.append(f"     Q加大 = Q × (1 + P/100)")
    o.append(f"          = {inp.Q} × (1 + {pct}/100)")
    o.append(f"          = {Q_inc:.4f} m\u00b3/s")
    o.append("")
    o.append("  2. 流量单位换算:")
    o.append(f"     Q' = Q加大 × 3600")
    o.append(f"        = {Q_inc:.4f} × 3600")
    o.append(f"        = {Q_inc_m3h:.2f} m\u00b3/h")
    o.append("")

    # ---- 三、管径计算 ----
    D = recommended.D
    d_mm = D * 1000
    A_full = math.pi * D ** 2 / 4.0

    section3_title = "【三、指定管径计算】" if is_manual else "【三、推荐管径计算】"
    o.append(section3_title)
    o.append("")
    step3_label = "指定管径:" if is_manual else "推荐管径:"
    o.append(f"  1. {step3_label}")
    o.append(f"     D = {D} m ({d_mm:.0f} mm)")
    o.append("")
    o.append("  2. 过水面积计算:")
    o.append(f"     A = π × D² / 4")
    o.append(f"       = π × {D}² / 4")
    o.append(f"       = {A_full:.6f} m²")
    o.append("")
    o.append("  3. 有压流速计算:")
    o.append(f"     V = Q / A")
    o.append(f"       = {inp.Q} / {A_full:.6f}")
    o.append(f"       = {recommended.V_press:.4f} m/s")
    o.append("")
    o.append("  4. 沿程水头损失计算:")
    o.append(f"     hf = f × (1000 × Q'^m) / (d^b)")
    o.append(f"        = {mat['f']} × (1000 × {Q_inc_m3h:.2f}^{mat['m']}) / ({d_mm:.0f}^{mat['b']})")
    o.append(f"        = {recommended.hf_friction_km:.4f} m/km")
    o.append("")
    o.append("  5. 局部水头损失计算:")
    _ratio = inp.local_loss_ratio
    o.append(f"     hj = {_ratio} × hf")
    o.append(f"         = {_ratio} × {recommended.hf_friction_km:.4f}")
    o.append(f"         = {recommended.hf_local_km:.4f} m/km")
    o.append("")
    o.append("  6. 总水头损失计算:")
    o.append(f"     hf总 = hf + hj")
    o.append(f"         = {recommended.hf_friction_km:.4f} + {recommended.hf_local_km:.4f}")
    o.append(f"         = {recommended.hf_total_km:.4f} m/km")
    o.append("")
    o.append("  7. 按管长折算总损失:")
    o.append(f"     H损 = hf总 × (L / 1000)")
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
    o.append(f"  3. 评价统计:")
    o.append(f"     全部 {len(all_candidates)} 种口径: 经济区 {eco_count} 个, 妥协区 {comp_count} 个, 兜底 {fallback_count} 个")
    o.append("")
    o.append(f"  4. 筛选结论:")
    if is_manual:
        o.append(f"     用户指定管径: D = {recommended.D} m ({recommended.D * 1000:.0f} mm)")
        o.append(f"     该管径属于「{recommended.category}」区")
        if auto_rec is not None and auto_cat:
            o.append(f"     自动推荐({auto_cat}区): D = {auto_rec.D} m ({auto_rec.D * 1000:.0f} mm)")
    elif category == "经济":
        o.append(f"     存在经济区口径，取最小管径: D = {recommended.D} m")
    elif category == "妥协":
        o.append(f"     无经济区口径，妥协区取最小管径: D = {recommended.D} m")
    else:
        o.append(f"     无经济区/妥协区口径，按 |V-0.9| 最小 + hf总 最小 兜底选取: D = {recommended.D} m")
        o.append(f"     注意: 未满足经济/妥协约束条件!")
    o.append("")

    # ---- 五、结果汇总 ----
    section5_label = "指定管径" if is_manual else "推荐管径"
    o.append(f"【五、{section5_label}结果】")
    o.append(f"  {section5_label}: D = {recommended.D} m ({recommended.D * 1000:.0f} mm)")
    o.append(f"  有压流速: V = {recommended.V_press:.4f} m/s")
    o.append(f"  沿程水损: hf = {recommended.hf_friction_km:.4f} m/km")
    o.append(f"  局部水损: hj = {recommended.hf_local_km:.4f} m/km")
    o.append(f"  总水损: hf总 = {recommended.hf_total_km:.4f} m/km")
    o.append(f"  按管长折算总损失: H损 = {recommended.h_loss_total_m:.4f} m (L={inp.length_m}m)")
    o.append(f"  所属类别: {recommended.category}")
    if recommended.flags:
        o.append(f"  标记: {', '.join(recommended.flags)}")
    o.append("")

    # ---- 指定模式：自动推荐对比（仅当自动推荐与指定D不同时） ----
    if is_manual and auto_rec is not None and auto_cat and abs(auto_rec.D - recommended.D) > 1e-6:
        o.append("【六、自动推荐对比】")
        o.append(f"  自动推荐管径: D = {auto_rec.D} m ({auto_rec.D * 1000:.0f} mm)")
        o.append(f"  有压流速: V = {auto_rec.V_press:.4f} m/s")
        o.append(f"  总水损: hf总 = {auto_rec.hf_total_km:.4f} m/km")
        o.append(f"  按管长折算总损失: H损 = {auto_rec.h_loss_total_m:.4f} m")
        o.append(f"  推荐类别: {auto_cat}")
        o.append("")

    # ---- 候选管径 ----
    has_auto_compare = (is_manual and auto_rec is not None and auto_cat
                        and abs(auto_rec.D - recommended.D) > 1e-6)
    section_num = "七" if has_auto_compare else "六"
    o.append(f"【{section_num}、前5候选管径】")
    eco_pool = sorted([c for c in all_candidates if c.category == "经济"], key=lambda c: c.D)
    comp_pool = sorted([c for c in all_candidates if c.category == "妥协"], key=lambda c: c.D)
    fb_pool = sorted(all_candidates, key=lambda c: (abs(c.V_press - 0.9), c.hf_total_km))

    if is_manual:
        # 指定D排首位，其余按 fallback 排序补足
        manual_c = [c for c in all_candidates if "用户指定" in c.flags]
        pool = list(manual_c[:1])
        seen_D = {c.D for c in pool}
        for c in fb_pool:
            if c.D not in seen_D:
                pool.append(c)
                seen_D.add(c.D)
                if len(pool) >= 5:
                    break
    else:
        if category == "经济":
            primary = eco_pool
        elif category == "妥协":
            primary = comp_pool
        else:
            primary = fb_pool
        pool = list(primary[:5])
        if len(pool) < 5:
            seen_D = {c.D for c in pool}
            for c in fb_pool:
                if c.D not in seen_D:
                    pool.append(c)
                    seen_D.add(c.D)
                    if len(pool) >= 5:
                        break

    pool = sorted(pool, key=lambda c: c.D)
    for i, c in enumerate(pool[:5]):
        marker = " ★" if "用户指定" in c.flags else ""
        o.append(f"  [{i+1}] D = {c.D} m ({c.D*1000:.0f}mm), V = {c.V_press:.4f} m/s, hf总 = {c.hf_total_km:.4f} m/km, H损 = {c.h_loss_total_m:.4f} m, 类别: {c.category}{marker}")
    o.append("")

    return "\n".join(o)
