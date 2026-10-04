# -*- coding: utf-8 -*-
"""单工况、批量报告与结果摘要共用的流速校核口径。"""

import math


def velocity_checks(params, result, *, strict_design=False):
    """返回设计、加大校核状态和说明；优先使用内核保留的未舍入流速。"""
    v_min = float(params.get('v_min', 0.1))
    v_max = float(params.get('v_max', 100.0))
    design = float(result.get('V_design_check', result.get('V_design', 0.0)))
    increased = float(result.get('V_increased_check', result.get('V_increased', 0.0)))
    use_increase = bool(params.get('use_increase', result.get('_use_increase', True)))
    design_ok = v_min < design < v_max if strict_design else v_min <= design <= v_max
    design_ok = math.isfinite(design) and design_ok and result.get('velocity_design_check_passed', True)
    increased_ok = not use_increase or (
        math.isfinite(increased) and 0 < increased <= v_max
        and result.get('velocity_increased_check_passed', True)
    )
    relation = '<' if strict_design else '≤'
    lines = [f"  设计流速限值校核: {v_min:g} {relation} V {relation} {v_max:g} m/s，"
             f"V={design:.6f} m/s → {'通过 ✓' if design_ok else '未通过 ✗'}"]
    if use_increase:
        lines.append(f"  加大流速不冲校核: V加大={increased:.6f} m/s ≤ {v_max:g} m/s "
                     f"→ {'通过 ✓' if increased_ok else '未通过 ✗'}")
    return bool(design_ok), bool(increased_ok), lines
