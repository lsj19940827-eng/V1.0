# -*- coding: utf-8 -*-
"""由流速和水损约束反求钢管最小净内径，再补壁厚并上取公称外径；供内核和结果解释共用。"""

import math

from calc_渠系计算算法内核.steel_pipe_design import (
    STEEL_DIAMETER_RULE, STEEL_DIAMETER_STEP_MM, STEEL_MAX_INNER_MM, get_steel_pipe_spec,
)


def steel_hydraulic_requirement(q, increased_q, material, rule, local_ratio):
    """分别反求流速上限、水损上限对应的净内径下限，保留完整计算快照。"""
    if not all(math.isfinite(value) and value > 0 for value in (q, increased_q)):
        raise ValueError('钢管设计及加大流量必须为正有限数')
    v_max, hf_max = rule['v_max'], rule['hf_max']
    f, m, b = material['f'], material['m'], material['b']
    # 对数计算避免大流量幂运算先溢出，超过规范内径范围由尺寸转换入口明确提示。
    velocity_mm = 1000 * math.sqrt(q) * math.sqrt(4 / (math.pi * v_max))
    loss_mm = math.exp((math.log(f) + math.log(1000) + m * (math.log(increased_q) + math.log(3600))
                        + math.log1p(local_ratio) - math.log(hf_max)) / b)
    return dict(
        version=1, design_q=q, increased_q=increased_q, f=f, m=m, b=b,
        local_ratio=local_ratio, velocity_limit=v_max, loss_limit=hf_max,
        velocity_min_inner_mm=velocity_mm, loss_min_inner_mm=loss_mm,
        required_hydraulic_inner_mm=max(velocity_mm, loss_mm), diameter_rule=STEEL_DIAMETER_RULE,
    )


def select_steel_outer_diameter(requirement, lining_mm=0):
    """给净内径补内衬和最小管壁，外径整百上取后重新求厚度并验证净内径。"""
    target = requirement['required_hydraulic_inner_mm']
    preliminary = get_steel_pipe_spec(target + 2 * lining_mm, 'inner', lining_mm)
    step = STEEL_DIAMETER_STEP_MM
    # 1e-7mm仅消除连续反算落在整数边界上的浮点噪声，不构成工程尺寸舍入。
    tolerance_mm = 1e-7
    first_outer = max(step, math.ceil((preliminary.outer_diameter_mm - tolerance_mm) / step) * step)
    outer = first_outer
    while True:
        spec = get_steel_pipe_spec(outer, 'outer', lining_mm)
        if spec.hydraulic_inner_diameter_mm + tolerance_mm >= target:
            break
        outer += step
    # 复核相邻下档，保证补厚与取整临界处没有跳过更小的合格外径。
    if outer > step:
        try:
            previous = get_steel_pipe_spec(outer - step, 'outer', lining_mm)
        except ValueError:
            previous = None
        if previous and previous.hydraulic_inner_diameter_mm + tolerance_mm >= target:
            raise ValueError('钢管最小外径取整校验失败，请检查尺寸边界')
    trace = dict(requirement, lining_mm=lining_mm,
                 required_steel_inner_mm=target + 2 * lining_mm,
                 preliminary_wall_mm=preliminary.nominal_wall_thickness_mm,
                 theoretical_outer_mm=preliminary.outer_diameter_mm,
                 first_rounded_outer_mm=first_outer, recommended_outer_mm=outer,
                 final_wall_mm=spec.nominal_wall_thickness_mm,
                 final_hydraulic_inner_mm=spec.hydraulic_inner_diameter_mm)
    return trace, spec


def steel_outer_neighbours(spec, lining_mm=0, count=5):
    """生成推荐外径、相邻下档和上档用于对比，不以旧候选序列限制最小值。"""
    step = STEEL_DIAMETER_STEP_MM
    diameters = [spec.outer_diameter_mm]
    if spec.outer_diameter_mm > step:
        diameters.append(spec.outer_diameter_mm - step)
    diameters += [spec.outer_diameter_mm + i * step for i in range(1, count + 1)]
    specs = []
    for diameter in diameters:
        try:
            candidate = get_steel_pipe_spec(diameter, 'outer', lining_mm)
        except ValueError:
            # 自动生成的邻档可能超过规范10m边界或被内衬占满，展示时不列这些无效邻档。
            continue
        specs.append(candidate)
        if len(specs) >= count:
            break
    return tuple(specs)


def steel_sizing_process(trace):
    """把保存的反算与外径上取快照写成可读详细过程，历史结果不重新反算。"""
    if not trace:
        return []
    lines = [
        '先求水力最小内径，再补两侧内衬和管壁，最后上取公称外径并复核。',
        f"流速上限 {trace['velocity_limit']:g} m/s；总水损上限 {trace['loss_limit']:g} m/km。",
        f"流速控制内径 d_v = 1000×sqrt(4×{trace['design_q']:g}/(π×{trace['velocity_limit']:g})) = {trace['velocity_min_inner_mm']:.4f} mm",
        f"水损控制内径 d_h = [{trace['f']:g}×1000×({trace['increased_q']:g}×3600)^{trace['m']:g}×(1+{trace['local_ratio']:g})/{trace['loss_limit']:g}]^(1/{trace['b']:g}) = {trace['loss_min_inner_mm']:.4f} mm",
        f"所需最小水力内径 = max({trace['velocity_min_inner_mm']:.4f}, {trace['loss_min_inner_mm']:.4f}) = {trace['required_hydraulic_inner_mm']:.4f} mm",
    ]
    if 'recommended_outer_mm' in trace:
        lines += [
            f"初算外径 = {trace['required_hydraulic_inner_mm']:.4f} + 2×{trace['lining_mm']:g} + 2×{trace['preliminary_wall_mm']:g} = {trace['theoretical_outer_mm']:.4f} mm",
            trace['diameter_rule'],
            f"上取并复核的最小公称外径 DN = {trace['recommended_outer_mm']:g} mm，最终壁厚 {trace['final_wall_mm']:g} mm，净内径 {trace['final_hydraulic_inner_mm']:g} mm。",
            '仍按实际净内径复核流速下限；未满足时仅作参考，不标为合格推荐。',
        ]
    return lines


def recommend_steel_pipe(inp, engine):
    """复用调用方内核的评价、结果类型和报告，完成钢管水力反算及外径唯一选径。"""
    if inp.manual_D is not None:
        raise ValueError('钢管请填写公称外径，不能同时传入旧水力内径 D')
    if inp.steel_dimension_basis != 'outer':
        raise ValueError('钢管新计算只接受外径输入；历史内径请先换算为外径')
    if inp.steel_diameter_candidates_mm is not None:
        raise ValueError('钢管自动选径已统一为100 mm整数倍，不再采用自定义候选序列')
    pct = inp.manual_increase_percent if inp.manual_increase_percent is not None else engine.get_flow_increase_percent(inp.Q)
    trace = steel_hydraulic_requirement(inp.Q, inp.Q * (1 + pct / 100), engine.PIPE_MATERIALS['钢管'],
                                        engine.ECONOMIC_RULE, inp.local_loss_ratio)
    auto = None
    candidates = []
    try:
        trace, spec = select_steel_outer_diameter(trace, inp.steel_lining_thickness_mm)
    except ValueError as exc:
        trace['selection_error'] = str(exc)
        if inp.manual_steel_diameter_mm is None:
            return engine.RecommendationResult(None, [], '无可用', str(exc), '\n'.join(steel_sizing_process(trace) + [str(exc)]))
    else:
        for candidate_spec in steel_outer_neighbours(spec, inp.steel_lining_thickness_mm):
            candidate = engine.evaluate_single_diameter(inp, candidate_spec.inner_diameter_m, product_spec=candidate_spec)
            candidate.steel_sizing_trace = dict(trace)
            candidates.append(candidate)
        auto = candidates[0]
        if auto.category == '兜底':
            auto.flags.append('外径上取后未满足流速下限，仅作参考')
    manual = inp.manual_steel_diameter_mm is not None
    rec = auto
    if manual:
        spec = get_steel_pipe_spec(inp.manual_steel_diameter_mm, 'outer', inp.steel_lining_thickness_mm)
        rec = engine.evaluate_single_diameter(inp, spec.inner_diameter_m, product_spec=spec)
        rec.flags.append('用户指定')
        rec.steel_sizing_trace = dict(trace)
    category = '指定' if manual else rec.category
    prefix = '用户指定公称外径' if manual else '最小公称外径推荐' if category != '兜底' else '整百外径参考（未满足全部水力条件）'
    reason = f'{prefix}：DN{rec.outer_diameter_mm:g} mm，水力内径 {rec.hydraulic_inner_diameter_mm:g} mm；V={rec.V_press:.4f} m/s，总水损={rec.hf_total_km:.4f} m/km。'
    steps = engine._build_process_text(inp, candidates, rec, category,
                                      auto_rec=auto if manual else None, auto_cat=auto.category if auto else None)
    return engine.RecommendationResult(rec, engine._order_for_display(candidates, rec)[:5], category,
                                       reason, steps, auto_recommended=auto if manual else None)
