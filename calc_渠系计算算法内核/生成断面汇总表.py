# -*- coding: utf-8 -*-
"""
断面尺寸及水力要素汇总表生成模块

根据各流量段参数，调用水力计算模块，按实际结构类型生成建筑物断面汇总表并导出为 Excel。
可直接用于 AutoCAD 制表（通过第三方插件粘贴）。

表格类型（按结果出现情况生成）:
  1. 矩形明渠断面尺寸及水力要素表
  2. 梯形明渠断面尺寸及水力要素表
  3. 圆拱直墙型隧洞断面尺寸及水力要素表（含 III/IV/V 类围岩）
  4. U形渡槽断面尺寸及水力要素表
  5. 矩形暗涵断面尺寸及水力要素表
  6. 圆管涵断面尺寸及水力要素表
  7. 倒虹吸断面尺寸及水力要素表（管道材质可选）
"""

import math
import re
import os
import sys
from typing import List, Dict, Any, Optional, Tuple

# ============================================================
# 导入同级计算模块
# ============================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from 明渠设计 import (
    quick_calculate_rectangular,
    quick_calculate_trapezoidal,
    quick_calculate_circular as _calc_circular_pipe,
)
from 隧洞设计 import (
    quick_calculate_horseshoe as _calc_horseshoe,
    quick_calculate_circular as _calc_tunnel_circular,
    solve_water_depth_horseshoe,
    calculate_horseshoe_outputs,
    get_flow_increase_percent as _tunnel_inc_pct,
)
from 渡槽设计 import quick_calculate_u as _calc_aqueduct_u
from 矩形暗涵设计 import quick_calculate_rectangular_culvert as _calc_rect_culvert

# ============================================================
# 常量
# ============================================================
PI = math.pi
V_MIN = 0.3
V_MAX = 6.0

SEGMENT_NAMES = [
    "第一流量段", "第二流量段", "第三流量段", "第四流量段",
    "第五流量段", "第六流量段", "第七流量段",
]


def _segment_name(idx: int) -> str:
    if idx <= 0:
        return "流量段"
    if idx <= len(SEGMENT_NAMES):
        return SEGMENT_NAMES[idx - 1]
    return f"第{idx}流量段"

# 隧洞围岩分类
ROCK_CLASSES = ["III类", "IV类", "V类"]
ROCK_LINING_DEFAULT = {
    "III类": {"t0": 0.35, "t": 0.30},
    "IV类":  {"t0": 0.40, "t": 0.40},
    "V类":   {"t0": 0.50, "t": 0.50},
}

# 倒虹吸管道材质 → 糙率
SIPHON_MATERIALS = {
    "PCCP管":       0.012,
    "球墨铸铁管":   0.012,
    "钢管":         0.011,
    "钢筋混凝土管": 0.014,
    "玻璃钢夹砂管": 0.009,
}

# ============================================================
# 推求水面线结果提取（尽可能复用计算结果）
# ============================================================

def _to_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip()
        if not s or s in ("-", "N/A", "nan"):
            return default
        return float(s)
    except Exception:
        return default


def _is_valid_num(val) -> bool:
    return isinstance(val, (int, float)) and val > 0


def _parse_flow_section_index(flow_section: str) -> Optional[int]:
    if not flow_section:
        return None
    s = str(flow_section).strip()
    if not s:
        return None
    m = re.search(r"\d+", s)
    if m:
        idx = int(m.group(0))
        if idx > 0:
            return idx
    for i, name in enumerate(SEGMENT_NAMES, start=1):
        if name in s:
            return i
    # 兼容中文数字（支持十位）
    cn_map = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    m_cn = re.search(r"[一二三四五六七八九十]+", s)
    if m_cn:
        cn = m_cn.group(0)
        if cn == "十":
            return 10
        if "十" in cn:
            parts = cn.split("十")
            tens = cn_map.get(parts[0], 1) if parts[0] else 1
            ones = cn_map.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
            return tens * 10 + ones
        if cn in cn_map:
            return cn_map[cn]
    return None


def _get_struct_name(node) -> str:
    st = getattr(node, "structure_type", None)
    if hasattr(st, "value"):
        return str(st.value)
    return str(st or "")


def _classify_structure(node) -> Optional[str]:
    name = _get_struct_name(node)
    params = getattr(node, "section_params", {}) or {}

    if getattr(node, "is_inverted_siphon", False) or "倒虹吸" in name:
        return "siphon"

    # 有压管道（与倒虹吸类似，但独立表格）
    if "有压管道" in name:
        return "pressure_pipe"

    # 隧洞细分：圆拱直墙型 / 圆形 / 马蹄形
    if "隧洞" in name or "隧" in name:
        if "圆形" in name:
            return "tunnel_circular"
        if "马蹄" in name:
            return "tunnel_horseshoe"
        if "圆拱直墙" in name:
            return "tunnel_arch"
        # 仅写"隧洞"时，依据参数判断
        d_val = _to_float(params.get("D", params.get("d", 0.0)), 0.0)
        r_val = _to_float(params.get("R_circle", params.get("R", 0.0)), 0.0)
        b_val = _to_float(params.get("B", params.get("b", 0.0)), 0.0)
        if d_val > 0 and b_val <= 0:
            return "tunnel_circular"
        if r_val > 0 and b_val <= 0:
            return "tunnel_horseshoe"
        return "tunnel_arch"

    # 渡槽细分：U形 / 矩形
    if "渡槽" in name:
        if "矩形" in name:
            return "aqueduct_rect"
        if "U" in name or "u" in name or "U" in name:
            return "aqueduct_u"
        # 仅写"渡槽"时，依据参数判断
        r_val = _to_float(params.get("R_circle", params.get("R", 0.0)), 0.0)
        if r_val > 0:
            return "aqueduct_u"
        return "aqueduct_rect"

    if "暗涵" in name:
        return "rect_culvert"

    # 明渠圆形 / 圆管涵
    if "明渠-圆形" in name or "圆形明渠" in name or "明渠圆形" in name or "圆管涵" in name:
        return "circular_channel"

    # 明渠梯形 / 矩形
    if "明渠-梯形" in name or ("明渠" in name and "梯形" in name) or "梯形明渠" in name:
        return "trap_channel"
    if "明渠-矩形" in name or ("明渠" in name and "矩形" in name) or "矩形明渠" in name:
        return "rect_channel"

    # 兼容旧值：仅写“矩形/梯形/圆形”
    if "梯形" in name:
        return "trap_channel"
    if "矩形" in name:
        return "rect_channel"
    if "圆形" in name:
        return "circular_channel"

    # 仅写“明渠”时，依据参数判断圆形/梯形/矩形
    if "明渠" in name:
        d_val = _to_float(params.get("D", params.get("R_circle", 0.0)), 0.0)
        if d_val > 0:
            return "circular_channel"
        m_val = _to_float(params.get("m", 0.0), 0.0)
        if m_val > 0:
            return "trap_channel"
        return "rect_channel"

    return None


def _assign_if_valid(target: Dict[str, Any], key: str, value: Any) -> None:
    if isinstance(value, (int, float)):
        if value <= 0:
            return
    else:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
    if key not in target or (isinstance(target.get(key), (int, float)) and target.get(key, 0) <= 0):
        target[key] = value


def _extract_segment_defaults_from_nodes(nodes) -> Tuple[Dict[str, Dict[int, Dict[str, Any]]], Dict[int, float]]:
    defaults = {
        "rect_channel": {},
        "trap_channel": {},
        "circular_channel": {},
        "tunnel_arch": {},
        "tunnel_circular": {},
        "tunnel_horseshoe": {},
        "aqueduct_u": {},
        "aqueduct_rect": {},
        "rect_culvert": {},
        "siphon": {},
        "pressure_pipe": {},
    }
    flow_qs: Dict[int, float] = {}

    if not nodes:
        return defaults, flow_qs

    for node in nodes:
        if getattr(node, "is_transition", False) or getattr(node, "is_auto_inserted_channel", False):
            continue

        seg_idx = _parse_flow_section_index(getattr(node, "flow_section", ""))
        if not seg_idx:
            continue

        q = _to_float(getattr(node, "flow", 0.0), 0.0)
        if q > 0:
            flow_qs[seg_idx] = max(flow_qs.get(seg_idx, 0.0), q)

        struct_key = _classify_structure(node)
        if not struct_key:
            continue

        target = defaults[struct_key].setdefault(seg_idx, {"name": _segment_name(seg_idx)})

        _assign_if_valid(target, "Q", q)
        _assign_if_valid(target, "n", _to_float(getattr(node, "roughness", 0.0), 0.0))

        slope_i = _to_float(getattr(node, "slope_i", 0.0), 0.0)
        if slope_i > 0:
            _assign_if_valid(target, "slope_inv", 1.0 / slope_i)

        params = getattr(node, "section_params", {}) or {}
        b_val = _to_float(params.get("B", params.get("b", params.get("b_design", 0.0))), 0.0)
        _assign_if_valid(target, "B", b_val)

        m_val = _to_float(params.get("m", 0.0), 0.0)
        _assign_if_valid(target, "m", m_val)

        d_val = _to_float(params.get("D", params.get("d", 0.0)), 0.0)
        _assign_if_valid(target, "D", d_val)

        r_val = _to_float(params.get("R_circle", params.get("R", 0.0)), 0.0)
        _assign_if_valid(target, "R", r_val)

        h_val = _to_float(getattr(node, "water_depth", 0.0), 0.0)
        if h_val <= 0:
            h_val = _to_float(params.get("h", params.get("water_depth", 0.0)), 0.0)
        _assign_if_valid(target, "H1", h_val)

        v_val = _to_float(getattr(node, "velocity", 0.0), 0.0)
        _assign_if_valid(target, "V", v_val)

        h_total = _to_float(getattr(node, "structure_height", 0.0), 0.0)
        _assign_if_valid(target, "H", math.ceil(h_total * 100) / 100)

        # 矩形渡槽倒角参数
        if struct_key == "aqueduct_rect":
            chamfer_angle = _to_float(params.get("chamfer_angle", 0.0), 0.0)
            _assign_if_valid(target, "chamfer_angle", chamfer_angle)
            chamfer_length = _to_float(params.get("chamfer_length", 0.0), 0.0)
            _assign_if_valid(target, "chamfer_length", chamfer_length)

        # 倒虹吸直径（优先D/结构高度）
        if struct_key == "siphon":
            dn_src = d_val if d_val > 0 else h_total
            if dn_src > 0:
                dn_mm = dn_src * 1000 if dn_src < 20 else dn_src
                _assign_if_valid(target, "DN_mm", dn_mm)

        # 有压管道直径（与倒虹吸类似）
        if struct_key == "pressure_pipe":
            dn_src = d_val if d_val > 0 else h_total
            if dn_src > 0:
                dn_mm = dn_src * 1000 if dn_src < 20 else dn_src
                _assign_if_valid(target, "DN_mm", dn_mm)

    return defaults, flow_qs


def _apply_overrides(row: Dict[str, Any], seg: Dict[str, Any], mapping: Dict[str, str]) -> None:
    for row_key, seg_key in mapping.items():
        if seg_key in seg:
            val = seg.get(seg_key)
            if isinstance(val, (int, float)):
                if val <= 0:
                    continue
            else:
                if val is None or (isinstance(val, str) and not val.strip()):
                    continue
            row[row_key] = val

# ============================================================
# 默认流量段参数（各表独立）
# ============================================================

def _default_segments_rect_channel():
    """矩形明渠默认参数"""
    Qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    slopes = [3000, 3000, 3000, 3000, 5555, 6666, 7777]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "slope_inv": slopes[i], "n": 0.014,
             "wall_t": 0.3, "tie_rod": "0.2×0.2"} for i in range(7)]

def _default_segments_trap_channel():
    """梯形明渠默认参数"""
    Qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    slopes = [3000, 3000, 3000, 3000, 5555, 6666, 7777]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "slope_inv": slopes[i], "n": 0.014,
             "m": 1.0, "wall_t": 0.3, "tie_rod": "0.2×0.2"} for i in range(7)]

def _default_segments_tunnel():
    """隧洞（圆拱直墙型）默认参数"""
    Qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    slopes = [2000, 2000, 2000, 2000, 2500, 2500, 2500]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "slope_inv": slopes[i], "n": 0.014}
            for i in range(7)]

# 向后兼容别名
_default_segments_tunnel_arch = _default_segments_tunnel

def _default_segments_tunnel_circular():
    """隧洞（圆形）默认参数"""
    Qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    slopes = [2000, 2000, 2000, 2000, 2500, 2500, 2500]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "slope_inv": slopes[i], "n": 0.014}
            for i in range(7)]

def _default_segments_tunnel_horseshoe():
    """隧洞（马蹄形）默认参数"""
    Qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    slopes = [2000, 2000, 2000, 2000, 2500, 2500, 2500]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "slope_inv": slopes[i], "n": 0.014}
            for i in range(7)]

def _default_segments_aqueduct():
    """渡槽（U形）默认参数"""
    Qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "slope_inv": 2000, "n": 0.014,
             "wall_t": 0.35} for i in range(7)]

# 向后兼容别名
_default_segments_aqueduct_u = _default_segments_aqueduct

def _default_segments_aqueduct_rect():
    """渡槽（矩形）默认参数"""
    Qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "slope_inv": 2000, "n": 0.014,
             "wall_t": 0.35} for i in range(7)]

def _default_segments_rect_culvert():
    """矩形暗涵默认参数"""
    Qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "slope_inv": 2500, "n": 0.014,
             "t0": 0.4, "t1": 0.4, "t2": 0.4} for i in range(7)]

def _default_segments_circular_pipe():
    """圆管涵默认参数"""
    Qs = [2.0, 1.3, 0.8, 0.6, 0.4, 0.2, 0.2]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "slope_inv": 3000, "n": 0.014,
             "pipe_material": "钢筋混凝土"} for i in range(7)]

def _default_segments_siphon():
    """倒虹吸默认参数"""
    Qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "DN_mm": 1500} for i in range(7)]

def _default_segments_pressure_pipe():
    """有压管道默认参数（与倒虹吸类似）"""
    Qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    return [{"name": _segment_name(i + 1), "Q": Qs[i], "DN_mm": 1500} for i in range(7)]


# ============================================================
# 1. 矩形明渠
# ============================================================

def compute_rect_channel(segments: List[Dict]) -> List[Dict]:
    rows = []
    for seg in segments:
        Q = seg["Q"]
        slope_inv = seg["slope_inv"]
        n = seg.get("n", 0.014)
        wall_t = seg.get("wall_t", 0.3)
        tie_rod = seg.get("tie_rod", "0.2×0.2")

        res = quick_calculate_rectangular(
            Q=Q, n=n, slope_inv=slope_inv, v_min=V_MIN, v_max=V_MAX,
        )
        if not res.get("success"):
            row = {"name": seg["name"], "Q": Q, "Q_inc": "", "slope_inv": slope_inv,
                   "n": n, "B": "", "H": "", "t": wall_t, "tie_rod": tie_rod,
                   "H1": "", "H2": "", "V": ""}
            _apply_overrides(row, seg, {
                "Q": "Q", "Q_inc": "Q_inc", "slope_inv": "slope_inv", "n": "n",
                "B": "B", "H": "H", "H1": "H1", "H2": "H2", "V": "V",
                "t": "t", "tie_rod": "tie_rod",
            })
            rows.append(row)
            continue

        row = {
            "name":      seg["name"],
            "Q":         Q,
            "Q_inc":     round(res["Q_increased"], 3),
            "slope_inv": slope_inv,
            "n":         n,
            "B":         round(res["b_design"], 2),
            "H":         round(res["h_prime"], 3),
            "t":         wall_t,
            "tie_rod":   tie_rod,
            "H1":        round(res["h_design"], 3),
            "H2":        round(res["h_increased"], 3),
            "V":         round(res["V_design"], 3),
        }
        _apply_overrides(row, seg, {
            "Q": "Q", "slope_inv": "slope_inv", "n": "n",
            "t": "t", "tie_rod": "tie_rod",
        })
        rows.append(row)
    return rows


# ============================================================
# 2. 梯形明渠
# ============================================================

def compute_trapezoid_channel(segments: List[Dict]) -> List[Dict]:
    rows = []
    for seg in segments:
        Q = seg["Q"]
        slope_inv = seg["slope_inv"]
        n = seg.get("n", 0.014)
        m = seg.get("m", 1.0)
        wall_t = seg.get("wall_t", 0.3)
        tie_rod = seg.get("tie_rod", "0.2×0.2")

        res = quick_calculate_trapezoidal(
            Q=Q, m=m, n=n, slope_inv=slope_inv, v_min=V_MIN, v_max=V_MAX,
        )
        if not res.get("success"):
            row = {"name": seg["name"], "Q": Q, "Q_inc": "", "slope_inv": slope_inv,
                   "n": n, "m": m, "B": "", "H": "", "t": wall_t, "tie_rod": tie_rod,
                   "H1": "", "H2": "", "V": "", "beta": ""}
            _apply_overrides(row, seg, {
                "Q": "Q", "Q_inc": "Q_inc", "slope_inv": "slope_inv", "n": "n",
                "m": "m", "B": "B", "H": "H", "H1": "H1", "H2": "H2", "V": "V",
                "t": "t", "tie_rod": "tie_rod", "beta": "beta",
            })
            rows.append(row)
            continue

        row = {
            "name":      seg["name"],
            "Q":         Q,
            "Q_inc":     round(res["Q_increased"], 3),
            "slope_inv": slope_inv,
            "n":         n,
            "m":         m,
            "B":         round(res["b_design"], 2),
            "H":         round(res["h_prime"], 3),
            "t":         wall_t,
            "tie_rod":   tie_rod,
            "H1":        round(res["h_design"], 3),
            "H2":        round(res["h_increased"], 3),
            "V":         round(res["V_design"], 3),
            "beta":      round(res.get("Beta_design", 0) or 0, 3) if res.get("Beta_design", 0) else "",
        }
        _apply_overrides(row, seg, {
            "Q": "Q", "slope_inv": "slope_inv", "n": "n",
            "m": "m", "t": "t", "tie_rod": "tie_rod",
        })
        rows.append(row)
    return rows


# ============================================================
# 3. 隧洞（圆拱直墙型 — 统一断面 + 围岩分类）
# ============================================================

def compute_tunnel(segments: List[Dict],
                   rock_lining: Dict = None,
                   unified: bool = False) -> Tuple[List[Dict], Dict]:
    """
    返回 (rows, tunnel_info)
      rows: 每个 segment × 3 行
      tunnel_info: {"B", "H_total", "H_straight", "R_arch", "theta_deg"}
    unified=True:  按最大流量段设计统一断面，各段分别求水深
    unified=False: 各流量段独立设计断面尺寸
    """
    if rock_lining is None:
        rock_lining = ROCK_LINING_DEFAULT

    override_map = {
        "Q": "Q", "slope_inv": "slope_inv", "n": "n",
    }

    def _design_one_seg(seg, B, H_total, H_straight, R_arch, theta_rad):
        """用给定断面尺寸为单个流量段求水深，返回 rows 列表。"""
        Q = seg["Q"]
        slope_inv = seg["slope_inv"]
        n = seg.get("n", 0.014)
        slope = 1.0 / slope_inv
        inc_pct = _tunnel_inc_pct(Q)
        Q_inc = Q * (1 + inc_pct / 100)

        h_d, ok_d = solve_water_depth_horseshoe(B, H_total, theta_rad, n, slope, Q)
        h_i, ok_i = solve_water_depth_horseshoe(B, H_total, theta_rad, n, slope, Q_inc)

        V_d = 0.0
        if ok_d and h_d > 0:
            out_d = calculate_horseshoe_outputs(B, H_total, theta_rad, h_d, n, slope)
            V_d = out_d["V"]

        seg_rows = []
        for rc in ROCK_CLASSES:
            row = {
                "name":       seg["name"],
                "Q":          Q,
                "Q_inc":      round(Q_inc, 3),
                "rock_class": rc,
                "slope_inv":  slope_inv,
                "n":          n,
                "B":          round(B, 2),
                "H_straight": round(H_straight, 2),
                "R_arch":     round(R_arch, 3),
                "t0":         rock_lining[rc]["t0"],
                "t":          rock_lining[rc]["t"],
                "H1":         round(h_d, 2) if ok_d else "",
                "H2":         round(h_i, 2) if ok_i else "",
                "V":          round(V_d, 2) if V_d > 0 else "",
            }
            _apply_overrides(row, seg, override_map)
            seg_rows.append(row)
        return seg_rows

    def _empty_rows_for_seg(seg):
        seg_rows = []
        for rc in ROCK_CLASSES:
            row = {"name": seg["name"], "Q": seg["Q"], "Q_inc": "",
                   "rock_class": rc, "slope_inv": seg["slope_inv"],
                   "n": seg.get("n", 0.014),
                   "B": "", "H_straight": "", "R_arch": "",
                   "t0": rock_lining[rc]["t0"], "t": rock_lining[rc]["t"],
                   "H1": "", "H2": "", "V": ""}
            _apply_overrides(row, seg, override_map)
            seg_rows.append(row)
        return seg_rows

    if unified:
        # --- 统一断面：用最大 Q 设计 ---
        max_seg = max(segments, key=lambda s: s["Q"])
        res_max = _calc_horseshoe(
            Q=max_seg["Q"], n=max_seg.get("n", 0.014),
            slope_inv=max_seg["slope_inv"], v_min=V_MIN, v_max=V_MAX,
        )
        if not res_max.get("success"):
            empty_info = {"B": 0, "H_total": 0, "H_straight": 0, "R_arch": 0, "theta_deg": 180}
            rows = []
            for seg in segments:
                rows.extend(_empty_rows_for_seg(seg))
            return rows, empty_info

        B = res_max["B"]
        H_total = res_max["H_total"]
        H_straight = res_max["H_straight"]
        theta_deg = res_max.get("theta_deg", 180.0)
        theta_rad = math.radians(theta_deg)
        sin_half = math.sin(theta_rad / 2)
        R_arch = (B / 2) / sin_half if abs(sin_half) > 1e-9 else B / 2

        tunnel_info = {"B": B, "H_total": H_total, "H_straight": H_straight,
                       "R_arch": R_arch, "theta_deg": theta_deg}

        rows = []
        for seg in segments:
            rows.extend(_design_one_seg(seg, B, H_total, H_straight, R_arch, theta_rad))
        return rows, tunnel_info
    else:
        # --- 独立断面：各流量段分别设计 ---
        rows = []
        first_info = None
        for seg in segments:
            res = _calc_horseshoe(
                Q=seg["Q"], n=seg.get("n", 0.014),
                slope_inv=seg["slope_inv"], v_min=V_MIN, v_max=V_MAX,
            )
            if not res.get("success"):
                rows.extend(_empty_rows_for_seg(seg))
                continue

            B = res["B"]
            H_total = res["H_total"]
            H_straight = res["H_straight"]
            theta_deg = res.get("theta_deg", 180.0)
            theta_rad = math.radians(theta_deg)
            sin_half = math.sin(theta_rad / 2)
            R_arch = (B / 2) / sin_half if abs(sin_half) > 1e-9 else B / 2

            if first_info is None:
                first_info = {"B": B, "H_total": H_total, "H_straight": H_straight,
                              "R_arch": R_arch, "theta_deg": theta_deg}

            rows.extend(_design_one_seg(seg, B, H_total, H_straight, R_arch, theta_rad))

        if first_info is None:
            first_info = {"B": 0, "H_total": 0, "H_straight": 0, "R_arch": 0, "theta_deg": 180}
        return rows, first_info

# 向后兼容别名
compute_tunnel_arch = compute_tunnel


# ============================================================
# 3b. 隧洞（圆形 — 统一断面 + 围岩分类）
# ============================================================

def compute_tunnel_circular(segments: List[Dict],
                            rock_lining: Dict = None,
                            unified: bool = False) -> Tuple[List[Dict], Dict]:
    """
    圆形隧洞计算。
    返回 (rows, tunnel_info)
      rows: 每个 segment × 3 行（III/IV/V类围岩）
      tunnel_info: {"D"}
    unified=True:  按最大流量段设计统一断面，各段分别求水深
    unified=False: 各流量段独立设计断面尺寸
    """
    if rock_lining is None:
        rock_lining = ROCK_LINING_DEFAULT

    from 隧洞设计 import solve_water_depth_circular, calculate_circular_outputs

    override_map = {
        "Q": "Q", "slope_inv": "slope_inv", "n": "n",
    }

    def _design_one_seg(seg, D):
        Q = seg["Q"]
        slope_inv = seg["slope_inv"]
        n = seg.get("n", 0.014)
        slope = 1.0 / slope_inv
        inc_pct = _tunnel_inc_pct(Q)
        Q_inc = Q * (1 + inc_pct / 100)

        h_d, ok_d = solve_water_depth_circular(D, n, slope, Q)
        h_i, ok_i = solve_water_depth_circular(D, n, slope, Q_inc)

        V_d = 0.0
        if ok_d and h_d > 0:
            out_d = calculate_circular_outputs(D, h_d, n, slope)
            V_d = out_d["V"]

        seg_rows = []
        for rc in ROCK_CLASSES:
            row = {
                "name":       seg["name"],
                "Q":          Q,
                "Q_inc":      round(Q_inc, 3),
                "rock_class": rc,
                "slope_inv":  slope_inv,
                "n":          n,
                "D":          round(D, 2),
                "t0":         rock_lining[rc]["t0"],
                "t":          rock_lining[rc]["t"],
                "H1":         round(h_d, 2) if ok_d else "",
                "H2":         round(h_i, 2) if ok_i else "",
                "V":          round(V_d, 2) if V_d > 0 else "",
            }
            _apply_overrides(row, seg, override_map)
            seg_rows.append(row)
        return seg_rows

    def _empty_rows_for_seg(seg):
        seg_rows = []
        for rc in ROCK_CLASSES:
            row = {"name": seg["name"], "Q": seg["Q"], "Q_inc": "",
                   "rock_class": rc, "slope_inv": seg["slope_inv"],
                   "n": seg.get("n", 0.014),
                   "D": "", "t0": rock_lining[rc]["t0"], "t": rock_lining[rc]["t"],
                   "H1": "", "H2": "", "V": ""}
            _apply_overrides(row, seg, override_map)
            seg_rows.append(row)
        return seg_rows

    if unified:
        # --- 统一断面：用最大 Q 设计 ---
        max_seg = max(segments, key=lambda s: s["Q"])
        res_max = _calc_tunnel_circular(
            Q=max_seg["Q"], n=max_seg.get("n", 0.014),
            slope_inv=max_seg["slope_inv"], v_min=V_MIN, v_max=V_MAX,
            manual_D=max_seg.get("D"),
        )
        if not res_max.get("success"):
            empty_info = {"D": 0}
            rows = []
            for seg in segments:
                rows.extend(_empty_rows_for_seg(seg))
            return rows, empty_info

        D = res_max["D"]
        tunnel_info = {"D": D}

        rows = []
        for seg in segments:
            rows.extend(_design_one_seg(seg, D))
        return rows, tunnel_info
    else:
        # --- 独立断面：各流量段分别设计 ---
        rows = []
        first_info = None
        for seg in segments:
            res = _calc_tunnel_circular(
                Q=seg["Q"], n=seg.get("n", 0.014),
                slope_inv=seg["slope_inv"], v_min=V_MIN, v_max=V_MAX,
            )
            if not res.get("success"):
                rows.extend(_empty_rows_for_seg(seg))
                continue

            D = res["D"]
            if first_info is None:
                first_info = {"D": D}

            rows.extend(_design_one_seg(seg, D))

        if first_info is None:
            first_info = {"D": 0}
        return rows, first_info


# ============================================================
# 3c. 隧洞（马蹄形 — 统一断面 + 围岩分类）
# ============================================================

def compute_tunnel_horseshoe(segments: List[Dict],
                             section_type: int = 1,
                             rock_lining: Dict = None,
                             unified: bool = False) -> Tuple[List[Dict], Dict]:
    """
    马蹄形隧洞计算。
    返回 (rows, tunnel_info)
      rows: 每个 segment × 3 行（III/IV/V类围岩）
      tunnel_info: {"R", "section_type_name"}
    section_type: 1=标准Ⅰ型, 2=标准Ⅱ型
    unified=True:  按最大流量段设计统一断面，各段分别求水深
    unified=False: 各流量段独立设计断面尺寸
    """
    if rock_lining is None:
        rock_lining = ROCK_LINING_DEFAULT

    from 隧洞设计 import (
        quick_calculate_horseshoe_std,
        solve_water_depth_horseshoe_std,
        calculate_horseshoe_std_outputs,
    )

    type_name = "马蹄形标准Ⅰ型" if section_type == 1 else "马蹄形标准Ⅱ型"

    override_map = {
        "Q": "Q", "slope_inv": "slope_inv", "n": "n",
    }

    def _design_one_seg(seg, R):
        Q = seg["Q"]
        slope_inv = seg["slope_inv"]
        n = seg.get("n", 0.014)
        slope = 1.0 / slope_inv
        inc_pct = _tunnel_inc_pct(Q)
        Q_inc = Q * (1 + inc_pct / 100)

        h_d, ok_d = solve_water_depth_horseshoe_std(section_type, R, n, slope, Q)
        h_i, ok_i = solve_water_depth_horseshoe_std(section_type, R, n, slope, Q_inc)

        V_d = 0.0
        if ok_d and h_d > 0:
            out_d = calculate_horseshoe_std_outputs(section_type, R, h_d, n, slope)
            V_d = out_d["V"]

        seg_rows = []
        for rc in ROCK_CLASSES:
            row = {
                "name":       seg["name"],
                "Q":          Q,
                "Q_inc":      round(Q_inc, 3),
                "rock_class": rc,
                "slope_inv":  slope_inv,
                "n":          n,
                "R":          round(R, 2),
                "t0":         rock_lining[rc]["t0"],
                "t":          rock_lining[rc]["t"],
                "H1":         round(h_d, 2) if ok_d else "",
                "H2":         round(h_i, 2) if ok_i else "",
                "V":          round(V_d, 2) if V_d > 0 else "",
            }
            _apply_overrides(row, seg, override_map)
            seg_rows.append(row)
        return seg_rows

    def _empty_rows_for_seg(seg):
        seg_rows = []
        for rc in ROCK_CLASSES:
            row = {"name": seg["name"], "Q": seg["Q"], "Q_inc": "",
                   "rock_class": rc, "slope_inv": seg["slope_inv"],
                   "n": seg.get("n", 0.014),
                   "R": "", "t0": rock_lining[rc]["t0"], "t": rock_lining[rc]["t"],
                   "H1": "", "H2": "", "V": ""}
            _apply_overrides(row, seg, override_map)
            seg_rows.append(row)
        return seg_rows

    if unified:
        # --- 统一断面：用最大 Q 设计 ---
        max_seg = max(segments, key=lambda s: s["Q"])
        res_max = quick_calculate_horseshoe_std(
            Q=max_seg["Q"], n=max_seg.get("n", 0.014),
            slope_inv=max_seg["slope_inv"], v_min=V_MIN, v_max=V_MAX,
            section_type=section_type,
            manual_r=max_seg.get("R"),
        )
        if not res_max.get("success"):
            empty_info = {"R": 0, "section_type_name": type_name}
            rows = []
            for seg in segments:
                rows.extend(_empty_rows_for_seg(seg))
            return rows, empty_info

        R = res_max["r"]
        tunnel_info = {"R": R, "section_type_name": type_name}

        rows = []
        for seg in segments:
            rows.extend(_design_one_seg(seg, R))
        return rows, tunnel_info
    else:
        # --- 独立断面：各流量段分别设计 ---
        rows = []
        first_info = None
        for seg in segments:
            res = quick_calculate_horseshoe_std(
                Q=seg["Q"], n=seg.get("n", 0.014),
                slope_inv=seg["slope_inv"], v_min=V_MIN, v_max=V_MAX,
                section_type=section_type,
            )
            if not res.get("success"):
                rows.extend(_empty_rows_for_seg(seg))
                continue

            R = res["r"]
            if first_info is None:
                first_info = {"R": R, "section_type_name": type_name}

            rows.extend(_design_one_seg(seg, R))

        if first_info is None:
            first_info = {"R": 0, "section_type_name": type_name}
        return rows, first_info


# ============================================================
# 4a. 渡槽 (U 形)
# ============================================================

def compute_aqueduct_u(segments: List[Dict]) -> List[Dict]:
    rows = []
    for seg in segments:
        Q = seg["Q"]
        slope_inv = seg["slope_inv"]
        n = seg.get("n", 0.014)
        wall_t = seg.get("wall_t", 0.35)

        res = _calc_aqueduct_u(Q=Q, n=n, slope_inv=slope_inv, v_min=V_MIN, v_max=V_MAX)
        if not res.get("success"):
            row = {"name": seg["name"], "Q": Q, "Q_inc": "", "slope_inv": slope_inv,
                   "n": n, "R": "", "H": "", "t": wall_t,
                   "H1": "", "H2": "", "V": "", "HB_ratio": ""}
            _apply_overrides(row, seg, {
                "Q": "Q", "Q_inc": "Q_inc", "slope_inv": "slope_inv", "n": "n",
                "R": "R", "H": "H", "H1": "H1", "H2": "H2", "V": "V",
                "t": "t",
            })
            rows.append(row)
            continue

        R = res["R"]
        H_total = res["H_total"]
        hb_ratio = H_total / (2 * R) if R > 0 else 0

        row = {
            "name":      seg["name"],
            "Q":         Q,
            "Q_inc":     round(res["Q_increased"], 3),
            "slope_inv": slope_inv,
            "n":         n,
            "R":         round(R, 2),
            "H":         round(H_total, 2),
            "t":         wall_t,
            "H1":        round(res["h_design"], 2),
            "H2":        round(res["h_increased"], 2),
            "V":         round(res["V_design"], 3),
            "HB_ratio":  round(hb_ratio, 3),
        }
        _apply_overrides(row, seg, {
            "Q": "Q", "slope_inv": "slope_inv", "n": "n",
            "t": "t",
        })
        rows.append(row)
    return rows


# ============================================================
# 4b. 渡槽 (矩形)
# ============================================================

def compute_aqueduct_rect(segments: List[Dict]) -> List[Dict]:
    from 渡槽设计 import quick_calculate_rect as _calc_aqueduct_rect
    rows = []
    for seg in segments:
        Q = seg["Q"]
        slope_inv = seg["slope_inv"]
        n = seg.get("n", 0.014)
        wall_t = seg.get("wall_t", 0.35)
        chamfer_angle = seg.get("chamfer_angle", 0)
        chamfer_length = seg.get("chamfer_length", 0)

        res = _calc_aqueduct_rect(Q=Q, n=n, slope_inv=slope_inv, v_min=V_MIN, v_max=V_MAX,
                                  chamfer_angle=chamfer_angle, chamfer_length=chamfer_length)
        if not res.get("success"):
            row = {"name": seg["name"], "Q": Q, "Q_inc": "", "slope_inv": slope_inv,
                   "n": n, "B": "", "H": "", "t": wall_t,
                   "chamfer_angle": chamfer_angle if chamfer_angle else "",
                   "chamfer_length": chamfer_length if chamfer_length else "",
                   "H1": "", "H2": "", "V": ""}
            _apply_overrides(row, seg, {
                "Q": "Q", "Q_inc": "Q_inc", "slope_inv": "slope_inv", "n": "n",
                "B": "B", "H": "H", "H1": "H1", "H2": "H2", "V": "V",
                "t": "t", "chamfer_angle": "chamfer_angle", "chamfer_length": "chamfer_length",
            })
            rows.append(row)
            continue

        row = {
            "name":           seg["name"],
            "Q":              Q,
            "Q_inc":          round(res["Q_increased"], 3),
            "slope_inv":      slope_inv,
            "n":              n,
            "B":              round(res["B"], 2),
            "H":              round(res["H_total"], 2),
            "t":              wall_t,
            "chamfer_angle":  res.get("chamfer_angle", 0) or "",
            "chamfer_length": res.get("chamfer_length", 0) or "",
            "H1":             round(res["h_design"], 2),
            "H2":             round(res["h_increased"], 2),
            "V":              round(res["V_design"], 3),
        }
        _apply_overrides(row, seg, {
            "Q": "Q", "slope_inv": "slope_inv", "n": "n",
            "t": "t", "chamfer_angle": "chamfer_angle", "chamfer_length": "chamfer_length",
        })
        rows.append(row)
    return rows


# ============================================================
# 5. 矩形暗涵
# ============================================================

def compute_rect_culvert(segments: List[Dict]) -> List[Dict]:
    rows = []
    for seg in segments:
        Q = seg["Q"]
        slope_inv = seg["slope_inv"]
        n = seg.get("n", 0.014)
        t0 = seg.get("t0", 0.4)
        t1 = seg.get("t1", 0.4)
        t2 = seg.get("t2", 0.4)

        res = _calc_rect_culvert(Q=Q, n=n, slope_inv=slope_inv, v_min=V_MIN, v_max=V_MAX)
        if not res.get("success"):
            row = {"name": seg["name"], "Q": Q, "Q_inc": "", "slope_inv": slope_inv,
                   "n": n, "B": "", "H": "", "t0": t0, "t1": t1, "t2": t2,
                   "H1": "", "H2": "", "V": ""}
            _apply_overrides(row, seg, {
                "Q": "Q", "Q_inc": "Q_inc", "slope_inv": "slope_inv", "n": "n",
                "B": "B", "H": "H", "H1": "H1", "H2": "H2", "V": "V",
                "t0": "t0", "t1": "t1", "t2": "t2",
            })
            rows.append(row)
            continue

        row = {
            "name":      seg["name"],
            "Q":         Q,
            "Q_inc":     round(res["Q_increased"], 3),
            "slope_inv": slope_inv,
            "n":         n,
            "B":         round(res["B"], 2),
            "H":         math.ceil(res["H"] * 100) / 100,
            "t0":        t0,
            "t1":        t1,
            "t2":        t2,
            "H1":        round(res["h_design"], 2),
            "H2":        round(res["h_increased"], 2),
            "V":         round(res["V_design"], 2),
        }
        _apply_overrides(row, seg, {
            "Q": "Q", "slope_inv": "slope_inv", "n": "n",
            "t0": "t0", "t1": "t1", "t2": "t2",
        })
        rows.append(row)
    return rows


# ============================================================
# 5. 圆管涵（无压自由面流）
# ============================================================

def compute_circular_pipe(segments: List[Dict]) -> List[Dict]:
    """使用明渠-圆形计算模块（无最小直径 2m 限制，适合圆管涵）"""
    rows = []
    for seg in segments:
        Q = seg["Q"]
        slope_inv = seg["slope_inv"]
        n = seg.get("n", 0.014)
        pipe_mat = seg.get("pipe_material", "钢筋混凝土")

        res = _calc_circular_pipe(Q=Q, n=n, slope_inv=slope_inv, v_min=V_MIN, v_max=V_MAX)
        if not res.get("success"):
            row = {"name": seg["name"], "Q": Q, "Q_inc": "", "slope_inv": slope_inv,
                   "n": n, "D": "", "pipe_material": pipe_mat,
                   "H1": "", "H2": "", "V": ""}
            _apply_overrides(row, seg, {
                "Q": "Q", "Q_inc": "Q_inc", "slope_inv": "slope_inv", "n": "n",
                "D": "D", "pipe_material": "pipe_material",
                "H1": "H1", "H2": "H2", "V": "V",
            })
            rows.append(row)
            continue

        D_val = res.get("D_design", 0) or 0
        Q_inc = res.get("Q_inc", 0) or 0
        y_d = res.get("y_d", 0) or 0
        y_i = res.get("y_i", 0) or 0
        V_d = res.get("V_d", 0) or 0

        row = {
            "name":          seg["name"],
            "Q":             Q,
            "Q_inc":         round(Q_inc, 3) if Q_inc else "",
            "slope_inv":     slope_inv,
            "n":             n,
            "D":             round(D_val, 1) if D_val else "",
            "pipe_material": pipe_mat,
            "H1":            round(y_d, 3) if y_d else "",
            "H2":            round(y_i, 3) if y_i else "",
            "V":             round(V_d, 3) if V_d else "",
        }
        _apply_overrides(row, seg, {
            "Q": "Q", "slope_inv": "slope_inv", "n": "n",
            "pipe_material": "pipe_material",
        })
        rows.append(row)
    return rows


# ============================================================
# 6. 倒虹吸（有压满管流）
# ============================================================

def compute_siphon(segments: List[Dict],
                   pipe_material: str = "球墨铸铁管") -> List[Dict]:
    rows = []
    for seg in segments:
        # 支持每段独立材质：优先使用段级 pipe_material，否则用全局参数
        seg_mat = seg.get("pipe_material", pipe_material)
        n = SIPHON_MATERIALS.get(seg_mat, 0.012)

        Q = seg["Q"]
        DN_mm = seg.get("DN_mm", 1500)
        D_m = DN_mm / 1000.0
        A = PI / 4 * D_m ** 2
        V = Q / A if A > 1e-9 else 0

        row = {
            "name":          seg["name"],
            "Q":             Q,
            "Q_inc":         round(Q * (1 + _tunnel_inc_pct(Q) / 100), 3),
            "n":             n,
            "DN_mm":         DN_mm,
            "pipe_material": seg_mat,
            "V":             round(V, 2),
        }
        _apply_overrides(row, seg, {
            "Q": "Q",
            "n": "n", "DN_mm": "DN_mm", "pipe_material": "pipe_material",
        })
        rows.append(row)
    return rows


# ============================================================
# 7. 有压管道（与倒虹吸类似，用于断面汇总表独立输出）
# ============================================================

def compute_pressure_pipe(segments: List[Dict],
                          pipe_material: str = "球墨铸铁管") -> List[Dict]:
    """有压管道断面汇总表计算（与倒虹吸表格格式一致）"""
    rows = []
    for seg in segments:
        # 支持每段独立材质：优先使用段级 pipe_material，否则用全局参数
        seg_mat = seg.get("pipe_material", pipe_material)
        n = SIPHON_MATERIALS.get(seg_mat, 0.012)

        Q = seg["Q"]
        DN_mm = seg.get("DN_mm", 1500)
        D_m = DN_mm / 1000.0
        A = PI / 4 * D_m ** 2
        V = Q / A if A > 1e-9 else 0

        row = {
            "name":          seg["name"],
            "Q":             Q,
            "Q_inc":         round(Q * (1 + _tunnel_inc_pct(Q) / 100), 3),
            "n":             n,
            "DN_mm":         DN_mm,
            "pipe_material": seg_mat,
            "V":             round(V, 2),
        }
        _apply_overrides(row, seg, {
            "Q": "Q",
            "n": "n", "DN_mm": "DN_mm", "pipe_material": "pipe_material",
        })
        rows.append(row)
    return rows


# ============================================================
# Excel 导出 — 公共辅助
# ============================================================

def _get_openpyxl():
    import openpyxl
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter
    thin = Side(style="thin")
    styles = {
        "border":     Border(left=thin, right=thin, top=thin, bottom=thin),
        "title_font": Font(name="宋体", bold=True, size=12),
        "hdr_font":   Font(name="宋体", bold=True, size=10),
        "cell_font":  Font(name="宋体", size=10),
        "center":     Alignment(horizontal="center", vertical="center", wrap_text=True),
        "hdr_fill":   PatternFill(fill_type=None),
    }
    return openpyxl, styles, get_column_letter


def _sc(ws, r, c, val, styles, font_key="cell_font"):
    """写入一个单元格并设置样式"""
    cell = ws.cell(row=r, column=c, value=val)
    cell.font = styles[font_key]
    cell.alignment = styles["center"]
    cell.border = styles["border"]
    return cell


def _write_title(ws, row, col_start, col_end, title, styles):
    """写入标题行（合并居中）"""
    ws.merge_cells(start_row=row, start_column=col_start,
                   end_row=row, end_column=col_end)
    cell = ws.cell(row=row, column=col_start, value=title)
    cell.font = styles["title_font"]
    cell.alignment = styles["center"]
    cell.border = styles["border"]
    # 给合并区域每个格子加边框
    for c in range(col_start, col_end + 1):
        ws.cell(row=row, column=c).border = styles["border"]


def _write_header_2row(ws, row_name, row_unit, col, name, unit, styles):
    """写入两行表头（名称行 + 单位行）"""
    if unit:
        _sc(ws, row_name, col, name, styles, "hdr_font").fill = styles["hdr_fill"]
        _sc(ws, row_unit, col, unit, styles, "hdr_font").fill = styles["hdr_fill"]
    else:
        # 无单位 → 合并两行
        ws.merge_cells(start_row=row_name, start_column=col,
                       end_row=row_unit, end_column=col)
        _sc(ws, row_name, col, name, styles, "hdr_font").fill = styles["hdr_fill"]
        ws.cell(row=row_unit, column=col).border = styles["border"]
        ws.cell(row=row_unit, column=col).fill = styles["hdr_fill"]


def _merge_vertical(ws, r_start, r_end, col, val, styles, font_key="cell_font"):
    """竖向合并多个单元格并写入值"""
    if r_start == r_end:
        _sc(ws, r_start, col, val, styles, font_key)
        return
    ws.merge_cells(start_row=r_start, start_column=col,
                   end_row=r_end, end_column=col)
    _sc(ws, r_start, col, val, styles, font_key)
    for r in range(r_start, r_end + 1):
        ws.cell(row=r, column=col).border = styles["border"]
        ws.cell(row=r, column=col).alignment = styles["center"]


def _set_col_width(ws, col, width, gcl):
    ws.column_dimensions[gcl(col)].width = width


# ============================================================
# Sheet 1: 矩形明渠
# ============================================================

def _write_rect_channel(ws, data, styles, gcl, col_offset=0):
    """写入矩形明渠表到 ws，从 col_offset+1 列开始"""
    C = col_offset  # 列偏移
    NCOLS = 12
    R1 = 1  # 标题行

    headers = [
        ("流量段",    None),
        ("设计流量",  "m³/s"),
        ("加大流量",  "m³/s"),
        ("1/底坡",    None),
        ("糙率",      None),
        ("底宽B",     "m"),
        ("高度H",     "m"),
        ("壁厚t",     "m"),
        ("拉杆尺寸",  "m"),
        ("设计水深H₁", "m"),
        ("加大水深H₂", "m"),
        ("设计流速",  "m/s"),
    ]
    col_widths = [14, 12, 12, 12, 10, 10, 10, 10, 12, 13, 13, 12]

    # 标题
    _write_title(ws, R1, C + 1, C + NCOLS, "矩形明渠断面尺寸及水力要素表", styles)
    # 表头
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    # 列宽
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)
    # 数据
    for ri, d in enumerate(data):
        r = R1 + 3 + ri
        vals = [d["name"], d["Q"], d.get("Q_inc", ""),
                f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
                d["n"], d.get("B", ""), d.get("H", ""), d.get("t", ""),
                d.get("tie_rod", ""), d.get("H1", ""), d.get("H2", ""), d.get("V", "")]
        for ci, v in enumerate(vals):
            _sc(ws, r, C + 1 + ci, v, styles)

    return NCOLS


# ============================================================
# Sheet 1b: 梯形明渠
# ============================================================

def _write_trapezoid_channel(ws, data, styles, gcl, col_offset=0):
    """写入梯形明渠表到 ws，从 col_offset+1 列开始"""
    C = col_offset
    NCOLS = 13
    R1 = 1

    headers = [
        ("流量段",      None),
        ("设计流量",    "m³/s"),
        ("加大流量",    "m³/s"),
        ("1/坡降",      None),
        ("糙率",        None),
        ("边坡系数m",   None),
        ("底宽B",       "m"),
        ("高度H",       "m"),
        ("壁厚t",       "m"),
        ("拉杆尺寸",     "m"),
        ("设计水深H₁",  "m"),
        ("加大水深H₂",  "m"),
        ("设计流速",    "m/s"),
    ]
    col_widths = [14, 12, 12, 12, 10, 12, 10, 10, 10, 12, 13, 13, 12]

    _write_title(ws, R1, C + 1, C + NCOLS, "梯形明渠断面尺寸及水力要素表", styles)
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)

    for ri, d in enumerate(data):
        r = R1 + 3 + ri
        vals = [d["name"], d["Q"], d.get("Q_inc", ""),
                f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
                d["n"], d.get("m", ""),
                d.get("B", ""), d.get("H", ""), d.get("t", ""),
                d.get("tie_rod", ""), d.get("H1", ""), d.get("H2", ""), d.get("V", "")]
        for ci, v in enumerate(vals):
            _sc(ws, r, C + 1 + ci, v, styles)

    return NCOLS


# ============================================================
# Sheet 2: 隧洞
# ============================================================

def _write_tunnel(ws, data, styles, gcl, col_offset=0):
    C = col_offset
    NCOLS = 14
    R1 = 1

    headers = [
        ("流量段",      None),
        ("设计流量",    "m³/s"),
        ("加大流量",    "m³/s"),
        ("围岩类型",    None),
        ("1/底坡",      None),
        ("糙率",        None),
        ("底宽B",       "m"),
        ("直墙高H",     "m"),
        ("顶拱半径R",   "m"),
        ("底板厚t₀",    "m"),
        ("边墙顶拱厚t", "m"),
        ("设计水深H₁",  "m"),
        ("加大水深H₂",  "m"),
        ("设计流速",    "m/s"),
    ]
    col_widths = [14, 12, 12, 12, 12, 10, 10, 10, 12, 11, 13, 13, 13, 12]

    _write_title(ws, R1, C + 1, C + NCOLS, "圆拱直墙型隧洞断面尺寸及水力要素表", styles)
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)

    # 数据：每 3 行为一组（III/IV/V）
    num_segments = len(data) // 3 if data else 0
    for si in range(num_segments):
        base_idx = si * 3
        r_start = R1 + 3 + base_idx
        r_end = r_start + 2
        d0 = data[base_idx]

        # 合并列: 流量段、设计流量、加大流量
        _merge_vertical(ws, r_start, r_end, C + 1, d0["name"], styles)
        _merge_vertical(ws, r_start, r_end, C + 2, d0["Q"], styles)
        _merge_vertical(ws, r_start, r_end, C + 3, d0.get("Q_inc", ""), styles)

        for j in range(3):
            d = data[base_idx + j]
            r = r_start + j
            vals = [
                d["rock_class"],
                f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
                d["n"],
                d.get("B", ""), d.get("H_straight", ""), d.get("R_arch", ""),
                d["t0"], d["t"],
                d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
            ]
            for ci, v in enumerate(vals):
                _sc(ws, r, C + 4 + ci, v, styles)

    return NCOLS

# 向后兼容别名
_write_tunnel_arch = _write_tunnel


# ============================================================
# Sheet 2b: 圆形隧洞
# ============================================================

def _write_tunnel_circular(ws, data, styles, gcl, col_offset=0):
    C = col_offset
    NCOLS = 12
    R1 = 1

    headers = [
        ("流量段",      None),
        ("设计流量",    "m³/s"),
        ("加大流量",    "m³/s"),
        ("围岩类型",    None),
        ("1/底坡",      None),
        ("糙率",        None),
        ("直径D",       "m"),
        ("底板厚t₀",    "m"),
        ("衬砌厚t",     "m"),
        ("设计水深H₁",  "m"),
        ("加大水深H₂",  "m"),
        ("设计流速",    "m/s"),
    ]
    col_widths = [14, 12, 12, 12, 12, 10, 10, 11, 11, 13, 13, 12]

    _write_title(ws, R1, C + 1, C + NCOLS, "圆形隧洞断面尺寸及水力要素表", styles)
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)

    num_segments = len(data) // 3 if data else 0
    for si in range(num_segments):
        base_idx = si * 3
        r_start = R1 + 3 + base_idx
        r_end = r_start + 2
        d0 = data[base_idx]

        _merge_vertical(ws, r_start, r_end, C + 1, d0["name"], styles)
        _merge_vertical(ws, r_start, r_end, C + 2, d0["Q"], styles)
        _merge_vertical(ws, r_start, r_end, C + 3, d0.get("Q_inc", ""), styles)

        for j in range(3):
            d = data[base_idx + j]
            r = r_start + j
            vals = [
                d["rock_class"],
                f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
                d["n"],
                d.get("D", ""),
                d["t0"], d["t"],
                d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
            ]
            for ci, v in enumerate(vals):
                _sc(ws, r, C + 4 + ci, v, styles)

    return NCOLS


# ============================================================
# Sheet 2c: 马蹄形隧洞
# ============================================================

def _write_tunnel_horseshoe(ws, data, styles, gcl, col_offset=0):
    C = col_offset
    NCOLS = 12
    R1 = 1

    headers = [
        ("流量段",      None),
        ("设计流量",    "m³/s"),
        ("加大流量",    "m³/s"),
        ("围岩类型",    None),
        ("1/底坡",      None),
        ("糙率",        None),
        ("半径R",       "m"),
        ("底板厚t₀",    "m"),
        ("衬砌厚t",     "m"),
        ("设计水深H₁",  "m"),
        ("加大水深H₂",  "m"),
        ("设计流速",    "m/s"),
    ]
    col_widths = [14, 12, 12, 12, 12, 10, 10, 11, 11, 13, 13, 12]

    _write_title(ws, R1, C + 1, C + NCOLS, "马蹄形隧洞断面尺寸及水力要素表", styles)
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)

    num_segments = len(data) // 3 if data else 0
    for si in range(num_segments):
        base_idx = si * 3
        r_start = R1 + 3 + base_idx
        r_end = r_start + 2
        d0 = data[base_idx]

        _merge_vertical(ws, r_start, r_end, C + 1, d0["name"], styles)
        _merge_vertical(ws, r_start, r_end, C + 2, d0["Q"], styles)
        _merge_vertical(ws, r_start, r_end, C + 3, d0.get("Q_inc", ""), styles)

        for j in range(3):
            d = data[base_idx + j]
            r = r_start + j
            vals = [
                d["rock_class"],
                f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
                d["n"],
                d.get("R", ""),
                d["t0"], d["t"],
                d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
            ]
            for ci, v in enumerate(vals):
                _sc(ws, r, C + 4 + ci, v, styles)

    return NCOLS


# ============================================================
# Sheet 3: 渡槽
# ============================================================

def _write_aqueduct(ws, data, styles, gcl, col_offset=0):
    C = col_offset
    NCOLS = 12
    R1 = 1

    headers = [
        ("流量段",     None),
        ("设计流量",   "m³/s"),
        ("加大流量",   "m³/s"),
        ("1/底坡",     None),
        ("糙率",       None),
        ("半径R",      None),
        ("槽深H",      "m"),
        ("壁厚t",      "m"),
        ("设计水深H₁", "m"),
        ("加大水深H₂", "m"),
        ("设计流速",   "m/s"),
        ("高宽比",     None),
    ]
    col_widths = [14, 12, 12, 12, 10, 10, 10, 10, 13, 13, 12, 10]

    _write_title(ws, R1, C + 1, C + NCOLS, "U形渡槽断面尺寸及水力要素表", styles)
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)

    for ri, d in enumerate(data):
        r = R1 + 3 + ri
        vals = [d["name"], d["Q"], d.get("Q_inc", ""),
                f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
                d["n"], d.get("R", ""), d.get("H", ""), d.get("t", ""),
                d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
                d.get("HB_ratio", "")]
        for ci, v in enumerate(vals):
            _sc(ws, r, C + 1 + ci, v, styles)

    return NCOLS

# 向后兼容别名
_write_aqueduct_u = _write_aqueduct


# ============================================================
# Sheet 3b: 矩形渡槽
# ============================================================

def _write_aqueduct_rect(ws, data, styles, gcl, col_offset=0):
    # 动态判断是否有倒角数据
    has_chamfer = any(d.get("chamfer_angle") for d in data)

    C = col_offset
    R1 = 1

    if has_chamfer:
        NCOLS = 13
        headers = [
            ("流量段",     None),
            ("设计流量",   "m³/s"),
            ("加大流量",   "m³/s"),
            ("1/底坡",     None),
            ("糙率",       None),
            ("底宽B",      "m"),
            ("槽深H",      "m"),
            ("壁厚t",      "m"),
            ("倒角角度",   "°"),
            ("倒角底边长", "m"),
            ("设计水深H₁", "m"),
            ("加大水深H₂", "m"),
            ("设计流速",   "m/s"),
        ]
        col_widths = [14, 12, 12, 12, 10, 10, 10, 10, 11, 11, 13, 13, 12]
    else:
        NCOLS = 11
        headers = [
            ("流量段",     None),
            ("设计流量",   "m³/s"),
            ("加大流量",   "m³/s"),
            ("1/底坡",     None),
            ("糙率",       None),
            ("底宽B",      "m"),
            ("槽深H",      "m"),
            ("壁厚t",      "m"),
            ("设计水深H₁", "m"),
            ("加大水深H₂", "m"),
            ("设计流速",   "m/s"),
        ]
        col_widths = [14, 12, 12, 12, 10, 10, 10, 10, 13, 13, 12]

    _write_title(ws, R1, C + 1, C + NCOLS, "矩形渡槽断面尺寸及水力要素表", styles)
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)

    for ri, d in enumerate(data):
        r = R1 + 3 + ri
        vals = [d["name"], d["Q"], d.get("Q_inc", ""),
                f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
                d["n"], d.get("B", ""), d.get("H", ""), d.get("t", "")]
        if has_chamfer:
            vals += [d.get("chamfer_angle", ""), d.get("chamfer_length", "")]
        vals += [d.get("H1", ""), d.get("H2", ""), d.get("V", "")]
        for ci, v in enumerate(vals):
            _sc(ws, r, C + 1 + ci, v, styles)

    return NCOLS


# ============================================================
# Sheet 4: 矩形暗涵
# ============================================================

def _write_rect_culvert(ws, data, styles, gcl, col_offset=0):
    C = col_offset
    NCOLS = 13
    R1 = 1

    headers = [
        ("流量段",     None),
        ("设计流量",   "m³/s"),
        ("加大流量",   "m³/s"),
        ("1/底坡",     None),
        ("糙率",       None),
        ("底宽B",      "m"),
        ("高度H",      "m"),
        ("底板厚t₀",   "m"),
        ("边墙厚t₁",   "m"),
        ("顶板厚t₂",   "m"),
        ("设计水深H₁", "m"),
        ("加大水深H₂", "m"),
        ("设计流速",   "m/s"),
    ]
    col_widths = [14, 12, 12, 12, 10, 10, 10, 11, 11, 11, 13, 13, 12]

    _write_title(ws, R1, C + 1, C + NCOLS, "矩形暗涵断面尺寸及水力要素表", styles)
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)

    for ri, d in enumerate(data):
        r = R1 + 3 + ri
        vals = [d["name"], d["Q"], d.get("Q_inc", ""),
                f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
                d["n"], d.get("B", ""), d.get("H", ""),
                d.get("t0", ""), d.get("t1", ""), d.get("t2", ""),
                d.get("H1", ""), d.get("H2", ""), d.get("V", "")]
        for ci, v in enumerate(vals):
            _sc(ws, r, C + 1 + ci, v, styles)

    return NCOLS


# ============================================================
# Sheet 5: 圆形明渠（圆管涵）
# ============================================================

def _write_circular_pipe(ws, data, styles, gcl, col_offset=0):
    C = col_offset
    NCOLS = 10
    R1 = 1

    headers = [
        ("流量段",      None),
        ("设计流量",    "m³/s"),
        ("加大流量",    "m³/s"),
        ("1/底坡",      None),
        ("糙率",        None),
        ("直径D",       "m"),
        ("管道材质",    None),
        ("设计水深H₁",  "m"),
        ("加大水深H₂",  "m"),
        ("设计流速v",   "m/s"),
    ]
    col_widths = [14, 12, 12, 12, 10, 10, 15, 13, 13, 12]

    _write_title(ws, R1, C + 1, C + NCOLS, "圆管涵断面尺寸及水力要素表", styles)
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)

    for ri, d in enumerate(data):
        r = R1 + 3 + ri
        vals = [d["name"], d["Q"], d.get("Q_inc", ""),
                f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
                d["n"], d.get("D", ""), d.get("pipe_material", ""),
                d.get("H1", ""), d.get("H2", ""), d.get("V", "")]
        for ci, v in enumerate(vals):
            _sc(ws, r, C + 1 + ci, v, styles)

    return NCOLS


# ============================================================
# Sheet 6: 倒虹吸
# ============================================================

def _write_siphon(ws, data, styles, gcl, col_offset=0):
    C = col_offset
    NCOLS = 7
    R1 = 1

    headers = [
        ("流量段",     None),
        ("设计流量",   "m³/s"),
        ("加大流量",   "m³/s"),
        ("糙率",       None),
        ("直径DN",     "mm"),
        ("管道材质",   None),
        ("设计流速v",  "m/s"),
    ]
    col_widths = [14, 12, 12, 10, 12, 15, 12]

    _write_title(ws, R1, C + 1, C + NCOLS, "倒虹吸断面尺寸及水力要素表", styles)
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)

    for ri, d in enumerate(data):
        r = R1 + 3 + ri
        vals = [d["name"], d["Q"], d.get("Q_inc", ""),
                d["n"], d.get("DN_mm", ""), d.get("pipe_material", ""),
                d.get("V", "")]
        for ci, v in enumerate(vals):
            _sc(ws, r, C + 1 + ci, v, styles)

    return NCOLS


# ============================================================
# Sheet 7: 有压管道
# ============================================================

def _write_pressure_pipe(ws, data, styles, gcl, col_offset=0):
    """有压管道 Excel 导出（与倒虹吸格式一致）"""
    C = col_offset
    NCOLS = 7
    R1 = 1

    headers = [
        ("流量段",     None),
        ("设计流量",   "m³/s"),
        ("加大流量",   "m³/s"),
        ("糙率",       None),
        ("直径DN",     "mm"),
        ("管道材质",   None),
        ("设计流速v",  "m/s"),
    ]
    col_widths = [14, 12, 12, 10, 12, 15, 12]

    _write_title(ws, R1, C + 1, C + NCOLS, "有压管道断面尺寸及水力要素表", styles)
    for i, (name, unit) in enumerate(headers):
        _write_header_2row(ws, R1 + 1, R1 + 2, C + 1 + i, name, unit, styles)
    for i, w in enumerate(col_widths):
        _set_col_width(ws, C + 1 + i, w, gcl)

    for ri, d in enumerate(data):
        r = R1 + 3 + ri
        vals = [d["name"], d["Q"], d.get("Q_inc", ""),
                d["n"], d.get("DN_mm", ""), d.get("pipe_material", ""),
                d.get("V", "")]
        for ci, v in enumerate(vals):
            _sc(ws, r, C + 1 + ci, v, styles)

    return NCOLS


# ============================================================
# 汇总 Sheet: 所有表格水平排列
# ============================================================

def _write_all_on_one_sheet(ws, tables, styles, gcl):
    """将多个表格水平排列在同一 Sheet（中间隔 1 列空白）"""
    offset = 0
    for writer, data in tables:
        ncols = writer(ws, data, styles, gcl, col_offset=offset)
        offset += ncols + 1  # 空 1 列


# ============================================================
# 主入口：生成 Excel
# ============================================================

def generate_excel(
    filepath: str,
    rect_channel_segs: List[Dict] = None,
    trap_channel_segs: List[Dict] = None,
    tunnel_segs: List[Dict] = None,
    tunnel_arch_segs: List[Dict] = None,
    tunnel_circular_segs: List[Dict] = None,
    tunnel_horseshoe_segs: List[Dict] = None,
    aqueduct_segs: List[Dict] = None,
    aqueduct_u_segs: List[Dict] = None,
    aqueduct_rect_segs: List[Dict] = None,
    rect_culvert_segs: List[Dict] = None,
    circular_pipe_segs: List[Dict] = None,
    siphon_segs: List[Dict] = None,
    siphon_material: str = "球墨铸铁管",
    pressure_pipe_segs: List[Dict] = None,
    pressure_pipe_material: str = "球墨铸铁管",
    rock_lining: Dict = None,
    table_order: List[str] = None,
    tunnel_unified_arch: bool = False,
    tunnel_unified_circular: bool = False,
    tunnel_unified_horseshoe: bool = False,
) -> str:
    """
    生成包含多种断面汇总表的 Excel 文件（按实际类型动态生成）。

    参数:
        filepath: 保存路径
        *_segs:   各表流量段参数列表（None 则用默认值）
        tunnel_segs: 旧参数（向后兼容，等同于 tunnel_arch_segs）
        aqueduct_segs: 旧参数（向后兼容，等同于 aqueduct_u_segs）
        siphon_material: 倒虹吸管道材质
        pressure_pipe_material: 有压管道材质
        rock_lining: 隧洞围岩衬砸厚度
        tunnel_unified_arch: 圆拱直墙型隧洞是否统一断面
        tunnel_unified_circular: 圆形隧洞是否统一断面
        tunnel_unified_horseshoe: 马蹄形隧洞是否统一断面

    返回:
        保存的文件路径
    """
    openpyxl, styles, gcl = _get_openpyxl()

    if rect_channel_segs is None:
        rect_channel_segs = _default_segments_rect_channel()
    if trap_channel_segs is None:
        trap_channel_segs = []

    # 隧洞：向后兼容旧 tunnel_segs 参数 → tunnel_arch_segs
    if tunnel_arch_segs is None and tunnel_segs is not None:
        tunnel_arch_segs = tunnel_segs
    if tunnel_arch_segs is None:
        tunnel_arch_segs = _default_segments_tunnel_arch()
    if tunnel_circular_segs is None:
        tunnel_circular_segs = []
    if tunnel_horseshoe_segs is None:
        tunnel_horseshoe_segs = []

    # 渡槽：向后兼容旧 aqueduct_segs 参数 → aqueduct_u_segs
    if aqueduct_u_segs is None and aqueduct_segs is not None:
        aqueduct_u_segs = aqueduct_segs
    if aqueduct_u_segs is None:
        aqueduct_u_segs = _default_segments_aqueduct_u()
    if aqueduct_rect_segs is None:
        aqueduct_rect_segs = []

    if rect_culvert_segs is None:
        rect_culvert_segs = _default_segments_rect_culvert()
    if circular_pipe_segs is None:
        circular_pipe_segs = _default_segments_circular_pipe()
    if siphon_segs is None:
        siphon_segs = _default_segments_siphon()
    if pressure_pipe_segs is None:
        pressure_pipe_segs = []

    # ---- 计算 ----
    d1 = compute_rect_channel(rect_channel_segs) if rect_channel_segs else []
    d1b = compute_trapezoid_channel(trap_channel_segs) if trap_channel_segs else []
    d2_arch, _ = compute_tunnel(tunnel_arch_segs, rock_lining, unified=tunnel_unified_arch) if tunnel_arch_segs else ([], {})
    d2_circ, _ = compute_tunnel_circular(tunnel_circular_segs, rock_lining, unified=tunnel_unified_circular) if tunnel_circular_segs else ([], {})
    d2_horse, d2_horse_info = compute_tunnel_horseshoe(tunnel_horseshoe_segs, rock_lining=rock_lining, unified=tunnel_unified_horseshoe) if tunnel_horseshoe_segs else ([], {})
    d3_u = compute_aqueduct_u(aqueduct_u_segs) if aqueduct_u_segs else []
    d3_rect = compute_aqueduct_rect(aqueduct_rect_segs) if aqueduct_rect_segs else []
    d4 = compute_rect_culvert(rect_culvert_segs) if rect_culvert_segs else []
    d5 = compute_circular_pipe(circular_pipe_segs) if circular_pipe_segs else []
    d6 = compute_siphon(siphon_segs, siphon_material) if siphon_segs else []
    d7 = compute_pressure_pipe(pressure_pipe_segs, pressure_pipe_material) if pressure_pipe_segs else []

    # 马蹄形隧洞 Sheet 名称动态显示型号
    horseshoe_sheet_name = "马蹄形隧洞"
    if d2_horse_info and d2_horse_info.get("section_type_name"):
        horseshoe_sheet_name = d2_horse_info["section_type_name"] + "隧洞"

    wb = openpyxl.Workbook()

    tables_map = {
        "rect_channel":     ("矩形明渠",          _write_rect_channel,       d1),
        "trap_channel":     ("梯形明渠",          _write_trapezoid_channel,  d1b),
        "tunnel_arch":      ("圆拱直墙型隧洞",    _write_tunnel,             d2_arch),
        "tunnel_circular":  ("圆形隧洞",          _write_tunnel_circular,    d2_circ),
        "tunnel_horseshoe": (horseshoe_sheet_name, _write_tunnel_horseshoe,   d2_horse),
        "aqueduct_u":       ("U形渡槽",           _write_aqueduct,           d3_u),
        "aqueduct_rect":    ("矩形渡槽",          _write_aqueduct_rect,      d3_rect),
        "rect_culvert":     ("矩形暗涵",          _write_rect_culvert,       d4),
        "circular_channel": ("圆形明渠(圆管涵)",   _write_circular_pipe,      d5),
        "siphon":           ("倒虹吸",            _write_siphon,             d6),
        "pressure_pipe":    ("有压管道",          _write_pressure_pipe,      d7),
        # 向后兼容旧 key
        "tunnel":           ("圆拱直墙型隧洞",    _write_tunnel,             d2_arch),
        "aqueduct":         ("U形渡槽",           _write_aqueduct,           d3_u),
    }
    
    if not table_order:
        table_order = ["rect_channel", "trap_channel",
                       "tunnel_arch", "tunnel_circular", "tunnel_horseshoe",
                       "aqueduct_u", "aqueduct_rect",
                       "rect_culvert", "circular_channel", "siphon", "pressure_pipe"]

    tables = []
    for key in table_order:
        info = tables_map.get(key)
        if not info:
            continue
        sheet_name, writer, data = info
        if data:
            tables.append((sheet_name, writer, data))

    # 如果没有有效表，至少保留矩形明渠
    if not tables:
        tables.append(("矩形明渠", _write_rect_channel, d1))

    # ---- 独立 Sheet ----
    first_name, first_writer, first_data = tables[0]
    ws_default = wb.active
    ws_default.title = first_name
    first_writer(ws_default, first_data, styles, gcl)

    for sheet_name, writer, data in tables[1:]:
        ws = wb.create_sheet(sheet_name)
        writer(ws, data, styles, gcl)

    # ---- 汇总 Sheet（水平排列） ----
    ws_all = wb.create_sheet("汇总(并列)", 0)
    _write_all_on_one_sheet(ws_all, [(w, d) for _, w, d in tables], styles, gcl)

    wb.save(filepath)
    return filepath


# ============================================================
# DXF 导出 — 通用表格绘制引擎
# ============================================================

# DXF 表格样式常量（单位: mm）
_DXF_ROW_H       = 7.0    # 普通行高
_DXF_HDR_ROW_H   = 10.0   # 表头行高
_DXF_TITLE_ROW_H = 10.0   # 标题行高
_DXF_TEXT_H       = 3.5    # 数据文字高度
_DXF_HDR_TEXT_H   = 3.5    # 表头文字高度
_DXF_TITLE_TEXT_H = 5.0    # 标题文字高度
_DXF_COL_PAD      = 3.5    # 单元格左右合计留白(mm)
_DXF_TABLE_GAP    = 8.0    # 多表格之间的纵向间距


_DXF_WIDTH_FACTOR = 0.7   # 全局宽度因子（仿宋 标准）
_DXF_FONT_NAME   = "仿宋"  # DXF 文字样式字体（Unicode版，支持下标字符）

# Unicode 下标字符 → 普通字符映射
_SUBSCRIPT_MAP = str.maketrans(
    '₀₁₂₃₄₅₆₇₈₉', '0123456789'
)
_SUBSCRIPT_CHARS = set('₀₁₂₃₄₅₆₇₈₉')

# Unicode 上标字符 → 普通字符映射
_SUPERSCRIPT_MAP = str.maketrans(
    '¹²³⁰⁴⁵⁶⁷⁸⁹', '1230456789'
)
_SUPERSCRIPT_CHARS = set('¹²³⁰⁴⁵⁶⁷⁸⁹')

# 上下标合并映射（用于 _dxf_sanitize）
_SCRIPT_MAP = {**dict(zip('₀₁₂₃₄₅₆₇₈₉', '0123456789')),
               **dict(zip('¹²³⁰⁴⁵⁶⁷⁸⁹', '1230456789'))}
_ALL_SCRIPT_CHARS = _SUBSCRIPT_CHARS | _SUPERSCRIPT_CHARS
_SANITIZE_MAP = str.maketrans(_SCRIPT_MAP)


def _dxf_sanitize(text):
    """将文本中的 Unicode 上下标字符转为普通数字（用于宽度估算等场景）。"""
    if text is None:
        return text
    return str(text).translate(_SANITIZE_MAP)


def _has_scripts(text):
    """检测文本是否包含 Unicode 上标或下标字符。"""
    if text is None:
        return False
    return any(c in _ALL_SCRIPT_CHARS for c in str(text))


def _to_mtext_script(text):
    """将含 Unicode 上下标的文本转换为 MTEXT 堆叠格式。

    下标示例: 'H₁' → 'H{\\H0.7x;\\S^ 1;}'    (上标留空，下标 = 1)
    上标示例: 'm³' → 'm{\\H0.7x;\\S3^ ;}' (上标 = 3，下标留空)

    AutoCAD MTEXT 的 \\S 堆叠命令: \\S上标^下标;
    用 {\\H0.7x; ...} 分组缩小字号。
    """
    if text is None:
        return ""
    result = []
    s = str(text)
    i = 0
    while i < len(s):
        if s[i] in _SUBSCRIPT_CHARS:
            # 收集连续的下标字符
            sub_chars = []
            while i < len(s) and s[i] in _SUBSCRIPT_CHARS:
                sub_chars.append(s[i].translate(_SUBSCRIPT_MAP))
                i += 1
            sub_text = ''.join(sub_chars)
            # MTEXT 下标: {\H0.7x;\S^ 下标;}  (上标为空)
            result.append("{\\H0.7x;\\S^ " + sub_text + ";}")
        elif s[i] in _SUPERSCRIPT_CHARS:
            # 收集连续的上标字符
            sup_chars = []
            while i < len(s) and s[i] in _SUPERSCRIPT_CHARS:
                sup_chars.append(s[i].translate(_SUPERSCRIPT_MAP))
                i += 1
            sup_text = ''.join(sup_chars)
            # MTEXT 上标: {\H0.7x;\S上标^ ;}  (下标为空)
            result.append("{\\H0.7x;\\S" + sup_text + "^ ;}")
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)


def _dxf_text_width(text, text_height):
    """估算 DXF 文字渲染宽度(mm)。
    中文字符宽度 ≈ text_height（仿宋方块字，em 宽 = 字高），
    ASCII 字符宽度 ≈ text_height × 0.6。
    注: 宽度因子仅影响 AutoCAD 渲染，不压缩估算值，以防列宽不足。
    """
    if text is None:
        return 0.0
    s = _dxf_sanitize(text)
    w = 0.0
    for ch in s:
        if ord(ch) > 0x7F:  # CJK / 全角
            w += text_height
        else:
            w += text_height * 0.6
    return w


def _dxf_auto_col_widths(headers, data_rows):
    """根据表头和数据内容自动计算每列宽度(mm)。"""
    ncols = len(headers)
    widths = [0.0] * ncols
    for ci, (name, unit) in enumerate(headers):
        w_name = _dxf_text_width(name, _DXF_HDR_TEXT_H)
        w_unit = _dxf_text_width(unit, _DXF_HDR_TEXT_H) if unit else 0.0
        widths[ci] = max(w_name, w_unit)
    for row in data_rows:
        for ci, val in enumerate(row):
            if ci >= ncols:
                break
            w = _dxf_text_width(val, _DXF_TEXT_H)
            if w > widths[ci]:
                widths[ci] = w
    return [w + _DXF_COL_PAD for w in widths]


def _dxf_draw_table(msp, origin_x, origin_y, title, headers, col_widths_mm,
                    data_rows, merge_groups=None, layer="TABLE"):
    """
    在 DXF modelspace 中绘制一个完整表格。

    参数:
        msp:           ezdxf modelspace
        origin_x/y:    表格左上角坐标（Y 向下为负）
        title:         标题文字
        headers:       [(name, unit), ...] — unit=None 时名称行与单位行合并
        col_widths_mm: [float, ...] 每列最小宽度(mm)，实际宽度按文字自适应
        data_rows:     [[val, val, ...], ...] 每行的单元格值列表
        merge_groups:  可选，[(col_indices, group_size), ...]
                       col_indices: 需要纵向合并的列索引列表
                       group_size:  每组合并的行数（如隧洞每段3行）
        layer:         DXF 图层名

    返回:
        表格总高度（正值，用于计算下一个表格的起始Y）
    """
    import ezdxf

    # 自适应列宽：取内容估算宽度与传入最小宽度的较大值
    auto_widths = _dxf_auto_col_widths(headers, data_rows)
    col_widths_mm = [max(a, m) for a, m in zip(auto_widths, col_widths_mm)]

    ncols = len(col_widths_mm)
    nrows = len(data_rows)

    # 计算列的 X 坐标（累加）
    col_x = [origin_x]
    for w in col_widths_mm:
        col_x.append(col_x[-1] + w)
    total_w = col_x[-1] - col_x[0]

    # Y 坐标（向下为负）
    y_title_top = origin_y
    y_title_bot = y_title_top - _DXF_TITLE_ROW_H
    y_hdr1_bot  = y_title_bot - _DXF_HDR_ROW_H
    y_hdr2_bot  = y_hdr1_bot - _DXF_HDR_ROW_H
    y_data_top  = y_hdr2_bot

    # 各数据行的 Y 坐标
    row_y = [y_data_top]
    for _ in range(nrows):
        row_y.append(row_y[-1] - _DXF_ROW_H)

    total_h = y_title_top - row_y[-1]

    dxfattribs_line = {"layer": layer}
    x_left, x_right = col_x[0], col_x[-1]

    # ---- 构建合并信息查找表 ----
    # merged_cells[ri][ci] = (group_start_row, group_size) 如果该单元格被合并
    merged_cells = {}
    if merge_groups:
        for merge_cols, group_size in merge_groups:
            if group_size <= 1:
                continue
            num_groups = nrows // group_size
            for gi in range(num_groups):
                r_start = gi * group_size
                for ci in merge_cols:
                    for offset in range(group_size):
                        ri = r_start + offset
                        if ri not in merged_cells:
                            merged_cells[ri] = {}
                        merged_cells[ri][ci] = (r_start, group_size)

    # ---- 绘制标题行 ----
    msp.add_line((x_left, y_title_top), (x_right, y_title_top), dxfattribs=dxfattribs_line)
    msp.add_line((x_left, y_title_bot), (x_right, y_title_bot), dxfattribs=dxfattribs_line)
    msp.add_line((x_left, y_title_top), (x_left, y_title_bot), dxfattribs=dxfattribs_line)
    msp.add_line((x_right, y_title_top), (x_right, y_title_bot), dxfattribs=dxfattribs_line)

    # ---- 绘制表头区 ----
    # 表头区有两行：名称行 + 单位行
    # 无单位的列需要合并两行（不画中间水平线）
    hdr_merged_cols = set()  # 需要合并表头两行的列索引
    for ci, (name, unit) in enumerate(headers):
        if not unit:
            hdr_merged_cols.add(ci)

    # 表头顶线（即标题底线已画）、中间分隔线、底线
    # 中间分隔线需要分段画（跳过合并列）
    for ci in range(ncols):
        if ci not in hdr_merged_cols:
            msp.add_line((col_x[ci], y_hdr1_bot), (col_x[ci + 1], y_hdr1_bot),
                         dxfattribs=dxfattribs_line)
    # 表头底线（完整画）
    msp.add_line((x_left, y_hdr2_bot), (x_right, y_hdr2_bot), dxfattribs=dxfattribs_line)
    # 表头区竖线
    for x in col_x:
        msp.add_line((x, y_title_bot), (x, y_hdr2_bot), dxfattribs=dxfattribs_line)

    # ---- 绘制数据区水平线（分段画，跳过合并单元格） ----
    # 第一行顶线和最后一行底线是完整的
    msp.add_line((x_left, y_data_top), (x_right, y_data_top), dxfattribs=dxfattribs_line)
    if nrows > 0:
        msp.add_line((x_left, row_y[-1]), (x_right, row_y[-1]), dxfattribs=dxfattribs_line)

    # 中间行分隔线（ri=1..nrows-1），跳过合并区域内部
    for ri in range(1, nrows):
        y_line = row_y[ri]
        # 标记每列是否需要跳过（处于合并区域的非首行）
        skip_col = set()
        if ri in merged_cells:
            for ci, (r_start, gs) in merged_cells[ri].items():
                if ri != r_start:  # 不是合并组的首行 → 跳过
                    skip_col.add(ci)
        # 分段画水平线：连续的非跳过列画一条线
        seg_start = None
        for ci in range(ncols):
            if ci in skip_col:
                if seg_start is not None:
                    msp.add_line((col_x[seg_start], y_line), (col_x[ci], y_line),
                                 dxfattribs=dxfattribs_line)
                    seg_start = None
            else:
                if seg_start is None:
                    seg_start = ci
        if seg_start is not None:
            msp.add_line((col_x[seg_start], y_line), (col_x[ncols], y_line),
                         dxfattribs=dxfattribs_line)

    # ---- 绘制数据区竖线 ----
    y_bottom = row_y[-1] if nrows > 0 else y_data_top
    for x in col_x:
        msp.add_line((x, y_data_top), (x, y_bottom), dxfattribs=dxfattribs_line)

    # ---- 局部辅助: 写入单元格文字（含下标自动识别） ----
    def _add_cell_text(text_str, cx, cy, h):
        """含上下标字符时用 MTEXT 堆叠，否则用普通 TEXT。"""
        if _has_scripts(text_str):
            mt = msp.add_mtext(
                _to_mtext_script(text_str),
                dxfattribs={"layer": layer, "char_height": h, "style": "Standard"}
            )
            mt.set_location(insert=(cx, cy), attachment_point=5)  # MIDDLE_CENTER
        else:
            msp.add_text(
                _dxf_sanitize(str(text_str)),
                dxfattribs={"layer": layer, "height": h,
                            "width": _DXF_WIDTH_FACTOR, "style": "Standard"}
            ).set_placement((cx, cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    # ---- 写入标题文字 ----
    title_cx = x_left + total_w / 2
    title_cy = (y_title_top + y_title_bot) / 2
    _add_cell_text(title, title_cx, title_cy, _DXF_TITLE_TEXT_H)

    # ---- 写入表头文字 ----
    for ci, (name, unit) in enumerate(headers):
        cx = (col_x[ci] + col_x[ci + 1]) / 2
        if unit:
            cy1 = (y_title_bot + y_hdr1_bot) / 2
            _add_cell_text(name, cx, cy1, _DXF_HDR_TEXT_H)
            cy2 = (y_hdr1_bot + y_hdr2_bot) / 2
            _add_cell_text(unit, cx, cy2, _DXF_HDR_TEXT_H)
        else:
            cy = (y_title_bot + y_hdr2_bot) / 2
            _add_cell_text(name, cx, cy, _DXF_HDR_TEXT_H)

    # ---- 写入数据文字（考虑合并） ----
    written_merged = set()  # 已写入的合并单元格 (r_start, ci)
    for ri, row_vals in enumerate(data_rows):
        for ci, val in enumerate(row_vals):
            if val is None or val == "":
                continue
            cx = (col_x[ci] + col_x[ci + 1]) / 2

            # 检查是否在合并区域
            if ri in merged_cells and ci in merged_cells[ri]:
                r_start, gs = merged_cells[ri][ci]
                key = (r_start, ci)
                if key in written_merged:
                    continue  # 该合并区域已写过文字
                written_merged.add(key)
                # 在合并区域的垂直中心写文字
                r_end = r_start + gs - 1
                cy = (row_y[r_start] + row_y[r_end + 1]) / 2
                # 使用首行的值
                merge_val = data_rows[r_start][ci]
                if merge_val is None or merge_val == "":
                    continue
                _add_cell_text(str(merge_val), cx, cy, _DXF_TEXT_H)
            else:
                cy = (row_y[ri] + row_y[ri + 1]) / 2
                _add_cell_text(str(val), cx, cy, _DXF_TEXT_H)

    return total_h


def _dxf_col_widths(excel_widths):
    """将 Excel 列宽列表转换为 DXF mm 最小宽度（作为下限参考）"""
    return [w * 0.8 for w in excel_widths]


# ============================================================
# DXF 各表类型数据构建
# ============================================================

def _dxf_build_rect_channel(data):
    title = "矩形明渠断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("1/底坡", None), ("糙率", None), ("底宽B", "m"), ("高度H", "m"),
        ("壁厚t", "m"), ("拉杆尺寸", "m"),
        ("设计水深H₁", "m"), ("加大水深H₂", "m"), ("设计流速", "m/s"),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 10, 8, 8, 9, 8, 10, 12, 12, 10])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
            d["n"], d.get("B", ""), d.get("H", ""), d.get("t", ""),
            d.get("tie_rod", ""), d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
        ])
    return title, headers, col_widths, rows, None


def _dxf_build_trapezoid_channel(data):
    title = "梯形明渠断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("1/坡降", None), ("糙率", None), ("边坡系数m", None),
        ("底宽B", "m"), ("高度H", "m"), ("壁厚t", "m"), ("拉杆尺寸", "m"),
        ("设计水深H₁", "m"), ("加大水深H₂", "m"), ("设计流速", "m/s"),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 10, 8, 10, 8, 9, 8, 10, 12, 12, 10])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
            d["n"], d.get("m", ""),
            d.get("B", ""), d.get("H", ""), d.get("t", ""),
            d.get("tie_rod", ""), d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
        ])
    return title, headers, col_widths, rows, None


def _dxf_build_tunnel(data):
    title = "圆拱直墙型隧洞断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("围岩类型", None), ("1/底坡", None), ("糙率", None),
        ("底宽B", "m"), ("直墙高H", "m"), ("顶拱半径R", "m"),
        ("底板厚t₀", "m"), ("边墙顶拱厚t", "m"),
        ("设计水深H₁", "m"), ("加大水深H₂", "m"), ("设计流速", "m/s"),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 10, 10, 8, 8, 9, 11, 10, 12, 12, 12, 10])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            d["rock_class"],
            f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
            d["n"],
            d.get("B", ""), d.get("H_straight", ""), d.get("R_arch", ""),
            d["t0"], d["t"],
            d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
        ])
    # 隧洞每3行为一组（III/IV/V类围岩），前3列合并
    merge = [([0, 1, 2], 3)] if len(data) >= 3 else None
    return title, headers, col_widths, rows, merge


def _dxf_build_tunnel_circular(data):
    title = "圆形隧洞断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("围岩类型", None), ("1/底坡", None), ("糙率", None),
        ("直径D", "m"), ("底板厚t₀", "m"), ("衬砌厚t", "m"),
        ("设计水深H₁", "m"), ("加大水深H₂", "m"), ("设计流速", "m/s"),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 10, 10, 8, 8, 10, 10, 12, 12, 10])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            d["rock_class"],
            f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
            d["n"],
            d.get("D", ""), d["t0"], d["t"],
            d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
        ])
    merge = [([0, 1, 2], 3)] if len(data) >= 3 else None
    return title, headers, col_widths, rows, merge


def _dxf_build_tunnel_horseshoe(data):
    title = "马蹄形隧洞断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("围岩类型", None), ("1/底坡", None), ("糙率", None),
        ("半径R", "m"), ("底板厚t₀", "m"), ("衬砌厚t", "m"),
        ("设计水深H₁", "m"), ("加大水深H₂", "m"), ("设计流速", "m/s"),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 10, 10, 8, 8, 10, 10, 12, 12, 10])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            d["rock_class"],
            f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
            d["n"],
            d.get("R", ""), d["t0"], d["t"],
            d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
        ])
    merge = [([0, 1, 2], 3)] if len(data) >= 3 else None
    return title, headers, col_widths, rows, merge


def _dxf_build_aqueduct_u(data):
    title = "U形渡槽断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("1/底坡", None), ("糙率", None), ("半径R", None),
        ("槽深H", "m"), ("壁厚t", "m"),
        ("设计水深H₁", "m"), ("加大水深H₂", "m"), ("设计流速", "m/s"),
        ("高宽比", None),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 10, 8, 8, 8, 8, 12, 12, 10, 8])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
            d["n"], d.get("R", ""), d.get("H", ""), d.get("t", ""),
            d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
            d.get("HB_ratio", ""),
        ])
    return title, headers, col_widths, rows, None


def _dxf_build_aqueduct_rect(data):
    title = "矩形渡槽断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("1/底坡", None), ("糙率", None), ("底宽B", "m"),
        ("槽深H", "m"), ("壁厚t", "m"),
        ("设计水深H₁", "m"), ("加大水深H₂", "m"), ("设计流速", "m/s"),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 10, 8, 8, 8, 8, 12, 12, 10])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
            d["n"], d.get("B", ""), d.get("H", ""), d.get("t", ""),
            d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
        ])
    return title, headers, col_widths, rows, None


def _dxf_build_rect_culvert(data):
    title = "矩形暗涵断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("1/底坡", None), ("糙率", None), ("底宽B", "m"),
        ("高度H", "m"), ("底板厚t₀", "m"), ("边墙厚t₁", "m"), ("顶板厚t₂", "m"),
        ("设计水深H₁", "m"), ("加大水深H₂", "m"), ("设计流速", "m/s"),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 10, 8, 8, 8, 10, 10, 10, 12, 12, 10])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
            d["n"], d.get("B", ""), d.get("H", ""),
            d.get("t0", ""), d.get("t1", ""), d.get("t2", ""),
            d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
        ])
    return title, headers, col_widths, rows, None


def _dxf_build_circular_pipe(data):
    title = "圆管涵断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("1/底坡", None), ("糙率", None), ("直径D", "m"),
        ("管道材质", None),
        ("设计水深H₁", "m"), ("加大水深H₂", "m"), ("设计流速v", "m/s"),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 10, 8, 8, 14, 12, 12, 10])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            f'1/{d["slope_inv"]:g}' if d.get("slope_inv") else "",
            d["n"], d.get("D", ""), d.get("pipe_material", ""),
            d.get("H1", ""), d.get("H2", ""), d.get("V", ""),
        ])
    return title, headers, col_widths, rows, None


def _dxf_build_siphon(data):
    title = "倒虹吸断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("糙率", None), ("直径DN", "mm"), ("管道材质", None),
        ("设计流速v", "m/s"),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 8, 10, 14, 10])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            d["n"], d.get("DN_mm", ""), d.get("pipe_material", ""),
            d.get("V", ""),
        ])
    return title, headers, col_widths, rows, None


def _dxf_build_pressure_pipe(data):
    """有压管道断面汇总表（与倒虹吸格式一致）"""
    title = "有压管道断面尺寸及水力要素表"
    headers = [
        ("流量段", None), ("设计流量", "m³/s"), ("加大流量", "m³/s"),
        ("糙率", None), ("直径DN", "mm"), ("管道材质", None),
        ("设计流速v", "m/s"),
    ]
    col_widths = _dxf_col_widths([12, 10, 10, 8, 10, 14, 10])
    rows = []
    for d in data:
        rows.append([
            d["name"], d["Q"], d.get("Q_inc", ""),
            d["n"], d.get("DN_mm", ""), d.get("pipe_material", ""),
            d.get("V", ""),
        ])
    return title, headers, col_widths, rows, None


# DXF 构建函数映射
_DXF_BUILDERS = {
    "rect_channel":     _dxf_build_rect_channel,
    "trap_channel":     _dxf_build_trapezoid_channel,
    "tunnel_arch":      _dxf_build_tunnel,
    "tunnel_circular":  _dxf_build_tunnel_circular,
    "tunnel_horseshoe": _dxf_build_tunnel_horseshoe,
    "aqueduct_u":       _dxf_build_aqueduct_u,
    "aqueduct_rect":    _dxf_build_aqueduct_rect,
    "rect_culvert":     _dxf_build_rect_culvert,
    "circular_channel": _dxf_build_circular_pipe,
    "siphon":           _dxf_build_siphon,
    "pressure_pipe":    _dxf_build_pressure_pipe,
    # 向后兼容
    "tunnel":           _dxf_build_tunnel,
    "aqueduct":         _dxf_build_aqueduct_u,
}


def generate_dxf(
    filepath: str,
    rect_channel_segs: List[Dict] = None,
    trap_channel_segs: List[Dict] = None,
    tunnel_segs: List[Dict] = None,
    tunnel_arch_segs: List[Dict] = None,
    tunnel_circular_segs: List[Dict] = None,
    tunnel_horseshoe_segs: List[Dict] = None,
    aqueduct_segs: List[Dict] = None,
    aqueduct_u_segs: List[Dict] = None,
    aqueduct_rect_segs: List[Dict] = None,
    rect_culvert_segs: List[Dict] = None,
    circular_pipe_segs: List[Dict] = None,
    siphon_segs: List[Dict] = None,
    siphon_material: str = "球墨铸铁管",
    pressure_pipe_segs: List[Dict] = None,
    pressure_pipe_material: str = "球墨铸铁管",
    rock_lining: Dict = None,
    table_order: List[str] = None,
    tunnel_unified_arch: bool = False,
    tunnel_unified_circular: bool = False,
    tunnel_unified_horseshoe: bool = False,
) -> str:
    """
    生成包含多种断面汇总表的 DXF 文件。
    参数与 generate_excel() 完全一致。
    所有表格纵向排列在模型空间中。

    返回:
        保存的文件路径
    """
    import ezdxf

    # ---- 参数默认值处理（与 generate_excel 一致） ----
    if rect_channel_segs is None:
        rect_channel_segs = _default_segments_rect_channel()
    if trap_channel_segs is None:
        trap_channel_segs = []
    if tunnel_arch_segs is None and tunnel_segs is not None:
        tunnel_arch_segs = tunnel_segs
    if tunnel_arch_segs is None:
        tunnel_arch_segs = _default_segments_tunnel_arch()
    if tunnel_circular_segs is None:
        tunnel_circular_segs = []
    if tunnel_horseshoe_segs is None:
        tunnel_horseshoe_segs = []
    if aqueduct_u_segs is None and aqueduct_segs is not None:
        aqueduct_u_segs = aqueduct_segs
    if aqueduct_u_segs is None:
        aqueduct_u_segs = _default_segments_aqueduct_u()
    if aqueduct_rect_segs is None:
        aqueduct_rect_segs = []
    if rect_culvert_segs is None:
        rect_culvert_segs = _default_segments_rect_culvert()
    if circular_pipe_segs is None:
        circular_pipe_segs = _default_segments_circular_pipe()
    if siphon_segs is None:
        siphon_segs = _default_segments_siphon()
    if pressure_pipe_segs is None:
        pressure_pipe_segs = []

    # ---- 计算 ----
    d1 = compute_rect_channel(rect_channel_segs) if rect_channel_segs else []
    d1b = compute_trapezoid_channel(trap_channel_segs) if trap_channel_segs else []
    d2_arch, _ = compute_tunnel(tunnel_arch_segs, rock_lining, unified=tunnel_unified_arch) if tunnel_arch_segs else ([], {})
    d2_circ, _ = compute_tunnel_circular(tunnel_circular_segs, rock_lining, unified=tunnel_unified_circular) if tunnel_circular_segs else ([], {})
    d2_horse, d2_horse_info_dxf = compute_tunnel_horseshoe(tunnel_horseshoe_segs, rock_lining=rock_lining, unified=tunnel_unified_horseshoe) if tunnel_horseshoe_segs else ([], {})
    d3_u = compute_aqueduct_u(aqueduct_u_segs) if aqueduct_u_segs else []
    d3_rect = compute_aqueduct_rect(aqueduct_rect_segs) if aqueduct_rect_segs else []
    d4 = compute_rect_culvert(rect_culvert_segs) if rect_culvert_segs else []
    d5 = compute_circular_pipe(circular_pipe_segs) if circular_pipe_segs else []
    d6 = compute_siphon(siphon_segs, siphon_material) if siphon_segs else []
    d7 = compute_pressure_pipe(pressure_pipe_segs, pressure_pipe_material) if pressure_pipe_segs else []

    # 马蹄形隧洞标题动态显示型号（与 generate_excel 一致）
    horseshoe_title = "马蹄形隧洞断面尺寸及水力要素表"
    if d2_horse_info_dxf and d2_horse_info_dxf.get("section_type_name"):
        horseshoe_title = d2_horse_info_dxf["section_type_name"] + "隧洞断面尺寸及水力要素表"

    data_map = {
        "rect_channel":     d1,
        "trap_channel":     d1b,
        "tunnel_arch":      d2_arch,
        "tunnel_circular":  d2_circ,
        "tunnel_horseshoe": d2_horse,
        "aqueduct_u":       d3_u,
        "aqueduct_rect":    d3_rect,
        "rect_culvert":     d4,
        "circular_channel": d5,
        "siphon":           d6,
        "pressure_pipe":    d7,
        "tunnel":           d2_arch,
        "aqueduct":         d3_u,
    }

    if not table_order:
        table_order = ["rect_channel", "trap_channel",
                       "tunnel_arch", "tunnel_circular", "tunnel_horseshoe",
                       "aqueduct_u", "aqueduct_rect",
                       "rect_culvert", "circular_channel", "siphon", "pressure_pipe"]

    # 收集有数据的表格
    tables = []
    for key in table_order:
        d = data_map.get(key)
        builder = _DXF_BUILDERS.get(key)
        if d and builder:
            tables.append((key, builder, d))

    if not tables:
        tables.append(("rect_channel", _dxf_build_rect_channel, d1))

    # ---- 创建 DXF 文件 ----
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # 设置中文字体样式：TrueType 仿宋_GB2312，宽度因子0.7
    if "Standard" in doc.styles:
        _sty = doc.styles.get("Standard")
    else:
        _sty = doc.styles.add("Standard")
    _sty.dxf.font = ""            # 清除 SHX 引用
    _sty.dxf.width = _DXF_WIDTH_FACTOR
    try:
        if "ACAD" not in doc.appids:
            doc.appids.new("ACAD")
    except Exception:
        pass
    _sty.set_xdata("ACAD", [(1000, _DXF_FONT_NAME), (1071, 0)])

    # 绘制各表格（纵向排列）
    current_y = 0.0
    for key, builder, d in tables:
        title, headers, col_widths, rows, merge = builder(d)
        # 马蹄形隧洞使用动态标题
        if key == "tunnel_horseshoe":
            title = horseshoe_title
        h = _dxf_draw_table(
            msp, 0.0, current_y,
            title, headers, col_widths, rows,
            merge_groups=merge, layer="TABLE"
        )
        current_y -= (h + _DXF_TABLE_GAP)

    doc.saveas(filepath)
    return filepath


# ============================================================
# Tkinter GUI 已移除，请使用 PySide6 版本：app_渠系计算前端/water_profile/cad_tools.py
# ============================================================
