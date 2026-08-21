# -*- coding: utf-8 -*-
"""泄水渠与陡坡计算原理构建，供界面、Word 和 Excel 导出共用。"""

from __future__ import annotations

from typing import Any

from .models import normalize_result, sanitize_formula_source


def _mapping(value: Any) -> dict[str, Any]:
    """把字典或对象安全整理为字典。"""
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _value(*candidates: Any, default: Any = "未提供") -> Any:
    """按顺序取第一个非空值，并保留合法零值。"""
    for value in candidates:
        if value not in (None, ""):
            return value
    return default


def _fmt(value: Any, unit: str = "", precision: int = 3, default: str = "未提供") -> str:
    """把数值整理成带单位的审查展示文本。"""
    if value in (None, ""):
        return default
    try:
        text = f"{float(value):.{precision}f}"
    except (TypeError, ValueError):
        text = str(value)
    return f"{text}{unit}"


def _summary_value(summary: dict[str, Any], key: str, default: str = "未提供") -> str:
    """读取结果汇总里的中文展示值。"""
    value = summary.get(key)
    return str(value) if value not in (None, "") else default


def _contains_latin(value: str) -> bool:
    """判断文本是否含有英文字符。"""
    return any(("a" <= char <= "z") or ("A" <= char <= "Z") for char in value)


def _display_section_type(value: Any) -> str:
    """把内部断面类型转换为中文展示。"""
    mapping = {
        "trapezoidal": "梯形断面",
        "rectangular": "矩形断面",
        "梯形": "梯形断面",
        "矩形": "矩形断面",
    }
    text = str(value or "")
    return mapping.get(text, "未识别" if _contains_latin(text) else str(value or "未识别"))


def _display_slope_type(value: Any) -> str:
    """把内部坡型转换为中文展示。"""
    mapping = {
        "steep": "陡坡",
        "mild": "缓坡",
        "critical": "临界坡",
        "unknown": "未识别",
    }
    text = str(value or "")
    return mapping.get(text, "未识别" if _contains_latin(text) else str(value or "未识别"))


def _display_control_source(value: Any) -> str:
    """把内部起点水深来源转换为中文展示。"""
    mapping = {
        "manual": "人工指定",
        "critical_depth": "临界水深",
        "critical": "临界水深",
        "inlet_control": "进口控制",
        "model_test": "模型试验",
        "free_connection": "自由衔接",
        "free_to_steep": "自由衔接",
        "actual": "实测控制",
    }
    text = str(value or "")
    return mapping.get(text, "未提供" if _contains_latin(text) else str(value or "未提供"))


def display_start_control_source(value: Any) -> str:
    """供导出模块复用的起点控制来源中文展示。"""
    return _display_control_source(value)


def _display_profile_type(value: Any) -> str:
    """把水面线内部类型转换为中文展示。"""
    mapping = {
        "b_1": "b_1 型壅水曲线",
        "b1": "b_1 型壅水曲线",
        "b_2": "b_2 型降水曲线",
        "b2": "b_2 型降水曲线",
        "steep_b2": "陡坡降水曲线",
        "mild_b1": "缓坡壅水曲线",
        "END_DEPTH_BY_LENGTH": "按已知长度推算",
        "LENGTH_BY_TWO_DEPTHS": "按两端水深推算",
        "UPSTREAM_END_CONTROL": "按上游控制推算",
        "NEAR_NORMAL_DEPTH": "推至正常水深附近",
    }
    text = str(value or "")
    return mapping.get(text, "未识别" if _contains_latin(text) else str(value or "未识别"))


def _display_inlet_connection(value: Any) -> str:
    """把入口连接形式内部值转换为中文展示。"""
    mapping = {
        "warped_surface": "扭曲面连接",
        "splay_wall": "八字墙连接",
        "diaphragm_wall": "横隔墙连接",
        "manual": "手动输入流量系数",
        "manual_coefficient": "手动输入流量系数",
    }
    text = str(value or "")
    return mapping.get(text.lower(), mapping.get(text, "未提供" if _contains_latin(text) else str(value or "未提供")))


def _formula_text(formula: str) -> str:
    """把界面渲染用公式转换为导出用中文可读公式。"""
    formula_map = {
        r"A=(b+mh)h,\quad \chi=b+2h\sqrt{1+m^2},\quad R=\frac{A}{\chi},\quad B=b+2mh": "A=(b+mh)h，χ=b+2h√(1+m²)，R=A/χ，B=b+2mh",
        r"Q=\frac{1}{n}AR^{2/3}i^{1/2}": "Q=(1/n)×A×R^(2/3)×i^(1/2)",
        r"\frac{\alpha Q^2}{g}=\frac{A_k^3}{B_k}": "αQ²/g=A_k³/B_k",
        r"i_k=\left(\frac{nQ}{A_kR_k^{2/3}}\right)^2": "i_k=(nQ/(A_kR_k^(2/3)))²",
        r"h_s=h_k\quad(\text{自由衔接}),\quad h_s=h_m\quad(\text{人工或实测控制})": "h_s=h_k（自由衔接）；h_s=h_m（人工或实测控制）",
        r"Q_{\text{过流}}=\varepsilon\mu b_c\sqrt{2g}H_0^{3/2}": "Q_过流=εμb_c√(2g)H_0^(3/2)",
        r"E_s=h+\alpha_e\frac{v^2}{2g},\quad J=\left(\frac{nQ}{AR^{2/3}}\right)^2,\quad \Delta s=\frac{E_{s,j+1}-E_{s,j}}{i-\overline{J}}": "E_s=h+α_e v²/(2g)，J=(nQ/(AR^(2/3)))²，Δs=(E_s,j+1-E_s,j)/(i-平均J)",
        r"h_b=\left(1+\frac{\zeta v}{100}\right)h,\quad H_{\text{侧墙}}=h_b+\Delta h_{\text{壅水}}+F_b": "h_b=(1+ζv/100)h，H_侧墙=h_b+Δh_壅水+F_b",
        r"h_c''=\frac{h_c'}{2}\left(\sqrt{1+8Fr_1^2}-1\right),\quad L_d=4.5h_c'',\quad d_d\geq \lambda h_c''-h_{\text{下游}}": "h_c''=(h_c'/2)(√(1+8Fr_1²)-1)，L_d=4.5h_c''，d_d≥λh_c''-h_下游",
        r"L_r\geq L_{\Delta b},\quad L_r\geq \eta h_c'',\quad L_r\geq L_{\text{最小}}": "L_r≥L_Δb，L_r≥ηh_c''，L_r≥L_最小",
        r"\text{结论}=\text{逐项校核结果}+\text{风险提示}": "结论=逐项校核结果+风险提示",
    }
    return formula_map.get(formula, formula)


def _source_by_name(result: Any) -> dict[str, str]:
    """按公式名称整理出处，兼容旧公式卡片字段。"""
    sources: dict[str, str] = {}
    for item in normalize_result(result).formulas:
        name = str(item.get("name") or item.get("title") or "")
        source = sanitize_formula_source(item.get("source") or item.get("出处") or "")
        if name and source:
            sources[name] = source
    return sources


def _principle(
    step: str,
    purpose: str,
    formula: str,
    variables: str,
    substitution: str,
    result: str,
    explanation: str,
    source: str,
) -> dict[str, str]:
    """生成单个计算原理步骤。"""
    return {
        "step": step,
        "purpose": purpose,
        "formula": formula,
        "formula_text": _formula_text(formula),
        "variables": variables,
        "substitution": substitution,
        "result": result,
        "explanation": explanation,
        "source": sanitize_formula_source(source),
    }


def build_calculation_principles(result: Any) -> list[dict[str, str]]:
    """根据一次计算结果生成审查级计算原理流程。"""
    data = _mapping(result)
    params = _mapping(data.get("input_params") or data.get("params") or data.get("input_data"))
    view = normalize_result(result)
    summary = view.summary
    hydraulic = _mapping(data.get("hydraulic"))
    normal = _mapping(hydraulic.get("normal"))
    critical = _mapping(hydraulic.get("critical"))
    start = _mapping(hydraulic.get("start"))
    profile = _mapping(data.get("profile"))
    start_control = _mapping(data.get("start_control"))
    inlet = _mapping(data.get("inlet_weir"))
    aeration = _mapping(data.get("aeration_and_sidewall"))
    jump = _mapping(data.get("hydraulic_jump") or data.get("downstream_energy_dissipation"))
    rectification = _mapping(jump.get("outlet_rectification"))
    checks = view.checks
    risks = view.risks
    sources = _source_by_name(result)

    design_flow = _summary_value(summary, "设计流量", _fmt(params.get("Q") or data.get("Q") or data.get("design_flow"), " 立方米/秒"))
    bed_slope = _summary_value(summary, "实际底坡", _fmt(params.get("i") or data.get("i") or data.get("bed_slope"), precision=6))
    normal_depth = _summary_value(summary, "正常水深", _fmt(hydraulic.get("normal_depth_m"), " 米"))
    critical_depth = _summary_value(summary, "临界水深", _fmt(hydraulic.get("critical_depth_m"), " 米"))
    critical_slope = _summary_value(summary, "临界底坡", _fmt(hydraulic.get("critical_slope"), precision=6))
    slope_type = _summary_value(summary, "坡型", _display_slope_type(hydraulic.get("slope_type")))
    start_depth = _summary_value(summary, "起点水深", _fmt(start.get("depth_m") or start_control.get("depth_m"), " 米"))
    end_depth = _summary_value(summary, "末端水深", _fmt(profile.get("end_depth_m"), " 米"))
    max_velocity = _summary_value(summary, "最大流速")
    max_froude = _summary_value(summary, "最大弗劳德数")
    profile_name = _display_profile_type(profile.get("water_profile_name") or hydraulic.get("water_profile_name") or data.get("water_profile_type"))
    inlet_connection = _display_inlet_connection(_value(inlet.get("connection_type"), params.get("inlet_connection_type"), default="未提供"))
    inlet_mu = _fmt(inlet.get("coefficient"), precision=3)
    inlet_epsilon = _fmt(inlet.get("contraction_coefficient"), precision=3, default="1.000")
    inlet_formula = str(inlet.get("coefficient_formula") or "按入口连接形式自动计算")
    inlet_source = str(inlet.get("coefficient_source") or sources.get("宽顶堰过流能力") or "GB 50288-2018 附录 N")
    inlet_head = _fmt(_value(inlet.get("head_m"), params.get("inlet_head"), params.get("H0"), default=None), " 米")
    inlet_scope = str(inlet.get("supported_scope") or "当前支持矩形跌口或等底宽陡坡入口校核")
    alpha_profile = _fmt(
        _value(
            params.get("alpha_profile"),
            params.get("profile_energy_alpha"),
            params.get("alpha_e"),
            hydraulic.get("water_profile_energy_alpha"),
            profile.get("water_profile_energy_alpha"),
            default=1.1,
        ),
        precision=3,
    )
    aeration_coefficient = _fmt(_value(aeration.get("aeration_coefficient"), params.get("aeration_coefficient"), default=1.2), precision=3)
    freeboard = _fmt(_value(aeration.get("freeboard_m"), params.get("sidewall_freeboard_m"), default=0.4), " 米")
    pool_factor = _fmt(_value(jump.get("pool_depth_factor"), params.get("pool_depth_factor"), default=1.10), precision=3)
    rectification_factor = _fmt(_value(rectification.get("length_factor"), params.get("outlet_rectification_factor"), default=10.0), precision=3)

    principles = [
        _principle(
            "基础断面与水力要素",
            "先把输入断面转换为过水面积、湿周、水力半径和水面宽，为后续全部水力计算提供统一基础。",
            r"A=(b+mh)h,\quad \chi=b+2h\sqrt{1+m^2},\quad R=\frac{A}{\chi},\quad B=b+2mh",
            "A 为过水面积，χ 为湿周，R 为水力半径，B 为水面宽，b 为底宽，m 为边坡系数，h 为水深。",
            f"断面类型={_display_section_type(hydraulic.get('section_type'))}，起点 A={_fmt(start.get('area_m2'), ' 平方米')}，R={_fmt(start.get('hydraulic_radius_m'), ' 米')}，B={_fmt(start.get('water_top_width_m'), ' 米')}",
            f"起点水深 {start_depth}，末端水深 {end_depth}",
            "同一断面下，水越深，过水面积和水力半径通常越大，过流能力也会随之变化。先算这些基础量，可以保证正常水深、临界水深和水面线使用同一套断面口径。",
            "明渠断面几何关系",
        ),
        _principle(
            "正常水深",
            "求渠道在给定底坡和糙率下能够稳定通过设计流量时的均匀流水深。",
            r"Q=\frac{1}{n}AR^{2/3}i^{1/2}",
            "Q 为流量，n 为糙率，A 为过水面积，R 为水力半径，i 为渠道底坡；求正常水深时，A 和 R 都随 h 变化。",
            f"Q={design_flow}，n={_fmt(params.get('n') or data.get('n') or data.get('roughness'), precision=4)}，i={bed_slope}，A={_fmt(normal.get('area_m2'), ' 平方米')}，R={_fmt(normal.get('hydraulic_radius_m'), ' 米')}",
            f"正常水深 h0={normal_depth}，对应流速 v={_fmt(normal.get('velocity_ms'), ' 米/秒')}",
            "程序改变水深试算，使曼宁公式算出的流量接近设计流量；这个水深代表渠道在均匀流条件下的自然稳定水深。",
            sources.get("曼宁公式", "GB 50288-2018 与明渠均匀流理论"),
        ),
        _principle(
            "临界水深",
            "找出断面比能最小、水流由缓流和急流分界的位置，用于确定入口控制和坡型。",
            r"\frac{\alpha Q^2}{g}=\frac{A_k^3}{B_k}",
            "α 为动能修正系数，g 为重力加速度，临界面积和临界水面宽均按临界水深对应断面计算。",
            f"Q={design_flow}，临界面积={_fmt(critical.get('area_m2'), ' 平方米')}，临界水面宽={_fmt(critical.get('water_top_width_m'), ' 米')}",
            f"临界水深 hk={critical_depth}，临界流速 v={_fmt(critical.get('velocity_ms'), ' 米/秒')}",
            "临界水深是能量状态的分界点。自由陡坡入口常会形成临界控制，因此它也是后续起点水深的重要依据。",
            sources.get("临界水深", "教材断面比能和临界流理论"),
        ),
        _principle(
            "坡型判别",
            "比较实际底坡和临界底坡，判断本工况应按陡坡、缓坡还是临界坡理解。",
            r"i_k=\left(\frac{nQ}{A_kR_k^{2/3}}\right)^2",
            "临界底坡按临界水深下的过水面积和水力半径反算，用来和实际底坡比较。",
            f"临界底坡={critical_slope}，实际底坡 i={bed_slope}，临界水深 hk={critical_depth}，正常水深 h0={normal_depth}",
            f"坡型判别结果：{slope_type}",
            "实际底坡大于临界底坡时，正常水深小于临界水深，水流更容易进入急流状态；这是陡坡水面线和下游消能判断的前提。",
            sources.get("临界底坡", "教材临界底坡理论"),
        ),
        _principle(
            "起点控制水深",
            "确定陡槽水面线从哪个水深开始计算，避免把上游缓坡正常水深直接当作陡坡入口水深。",
            r"h_s=h_k\quad(\text{自由衔接}),\quad h_s=h_m\quad(\text{人工或实测控制})",
            "h_s 为陡槽起点水深，h_k 为临界水深，h_m 为人工指定或实测控制水深。",
            f"来源={_display_control_source(start_control.get('source'))}，控制水深={_fmt(start_control.get('depth_m'), ' 米')}，临界水深={critical_depth}",
            f"采用起点水深 {start_depth}",
            str(start_control.get("message") or "自由衔接时通常按临界水深作为陡槽入口控制；若用户给出人工或实测水深，则优先采用该控制值。"),
            "入口控制段计算",
        ),
        _principle(
            "入口过流能力",
            "检查跌口或等底宽陡坡入口是否具备通过设计流量的能力。",
            r"Q_{\text{过流}}=\varepsilon\mu b_c\sqrt{2g}H_0^{3/2}",
            "Q_过流 为入口过流能力，ε 为侧收缩系数，μ 为流量系数，b_c 为控制断面宽度，H_0 为计入堰前流速水头的堰上总水头。",
            f"设计流量 Q={design_flow}，堰上总水头 H_0={inlet_head}，入口连接形式={inlet_connection}，流量系数={inlet_mu}，侧收缩系数={inlet_epsilon}，系数公式={inlet_formula}，入口能力比={_summary_value(summary, '入口过流能力比')}，{inlet_scope}",
            str(inlet.get("message") or "未配置跌口或入口控制参数时，仅保留公式和校核口径，不强行判断。"),
            f"流量系数来源={inlet_source}；侧收缩系数={inlet_epsilon} 表示按无明显边界收缩或未另行折减处理。当前 H_0 由用户直接输入，本版本不自动由堰前水深和流速水头推导。当入口过流能力小于设计流量时，即使陡槽本身能过流，入口也可能成为控制瓶颈。",
            inlet_source,
        ),
        _principle(
            "水面线逐段计算",
            "沿陡槽长度逐段推算水深、水位、流速、弗劳德数和水力坡度。",
            r"E_s=h+\alpha_e\frac{v^2}{2g},\quad J=\left(\frac{nQ}{AR^{2/3}}\right)^2,\quad \Delta s=\frac{E_{s,j+1}-E_{s,j}}{i-\overline{J}}",
            "E_s 为断面比能，v 为流速，J 为水力坡度，Δs 为相邻两个试算水深之间的距离，底坡与平均水力坡度的差值决定沿程推进距离。",
            f"起点水深={start_depth}，末端水深={end_depth}，水面线动能修正系数={alpha_profile}，最大流速={max_velocity}，最大弗劳德数={max_froude}",
            f"水面线类型：{profile_name}",
            "程序从起点水深开始，按能量变化逐段寻找下一个水深位置；每个沿程点再换算成水位、流速和流态，用于纵断面图和表3轻量接口。",
            sources.get("逐段能量方程", "逐段试算法"),
        ),
        _principle(
            "掺气水深与侧墙高度",
            "估算高速水流掺气后的水深增量，并给出侧墙高度建议。",
            r"h_b=\left(1+\frac{\zeta v}{100}\right)h,\quad H_{\text{侧墙}}=h_b+\Delta h_{\text{壅水}}+F_b",
            "h_b 为掺气水深，ζ 为掺气系数，v 为流速，H_侧墙 为建议侧墙高度，F_b 为安全超高。",
            f"掺气系数={aeration_coefficient}，最大掺气水深={_summary_value(summary, '最大掺气水深')}，安全超高={freeboard}",
            f"建议侧墙高度={_summary_value(summary, '建议侧墙高度')}",
            str(aeration.get("message") or "高流速会夹带空气，使水体体积增大；侧墙顶线需要在清水水深基础上考虑掺气、壅水和安全超高。"),
            sources.get("掺气水深", "GB 50288-2018 附录 N"),
        ),
        _principle(
            "水跃与消力池",
            "用陡槽末端跃前水深和流速估算跃后水深，再与下游控制水深比较，判断消力池需求。",
            r"h_c''=\frac{h_c'}{2}\left(\sqrt{1+8Fr_1^2}-1\right),\quad L_d=4.5h_c'',\quad d_d\geq \lambda h_c''-h_{\text{下游}}",
            "h_c' 为跃前水深，h_c'' 为跃后共轭水深，Fr_1 为跃前弗劳德数，L_d 为池长，d_d 为池深，h_下游 为下游控制水深。",
            f"跃前水深={_fmt(jump.get('pre_jump_depth_m'), ' 米')}，跃前弗劳德数={_fmt(jump.get('pre_jump_froude'), precision=3)}，控制水深={_fmt(jump.get('control_depth_m'), ' 米')}，池深系数={pool_factor}",
            f"跃后共轭水深={_summary_value(summary, '跃后共轭水深')}，建议池长={_summary_value(summary, '建议消力池长度')}，建议池深={_summary_value(summary, '建议消力池深度')}",
            str(jump.get("message") or "若尾水不足，自由水跃可能向下游移动，需要通过消力池或出口防冲措施稳定水跃位置。"),
            sources.get("矩形断面共轭水深") or sources.get("消力池初拟尺寸", "水跃理论"),
        ),
        _principle(
            "出口整流段",
            "按出口扩散、跃后水深倍数和最小防冲长度共同确定出口连接段建议长度。",
            r"L_r\geq L_{\Delta b},\quad L_r\geq \eta h_c'',\quad L_r\geq L_{\text{最小}}",
            "L_r 为出口整流段长度，L_Δb 为宽度渐变所需长度，η 为跃后水深倍数控制系数，L_最小 为最小长度。",
            f"宽度渐变长度={_fmt(rectification.get('width_transition_length_m'), ' 米')}，能量控制长度={_fmt(rectification.get('energy_length_m'), ' 米')}，最小长度={_fmt(rectification.get('minimum_length_m'), ' 米')}，整流长度系数={rectification_factor}",
            f"建议出口整流段={_summary_value(summary, '建议出口整流段')}",
            str(rectification.get("message") or "出口段不只看宽度变化，还要兼顾跃后水深和防冲需要，最终取几个控制条件中的较大值。"),
            sources.get("出口整流段", "出口连接段整流布置校核口径"),
        ),
        _principle(
            "规范校核与风险提示",
            "把计算结果转化为是否需要复核的工程提示，便于审查人员快速定位风险。",
            r"\text{结论}=\text{逐项校核结果}+\text{风险提示}",
            "校核项目来自纵坡、流速、湿周、入口能力、尾水条件等结果；风险提示不阻止计算，但需要设计人员复核。",
            f"校核项数量={len(checks)}，风险提示数量={len(risks)}",
            "通过" if not risks else "需复核",
            "计算原理只说明水力计算过程；最终采用前仍应结合规范条文、工程重要性、地形地质和下游防冲条件进行人工复核。",
            "GB 50288-2018 与工程复核口径",
        ),
    ]
    return principles


def build_precalculation_principles(params: dict[str, Any]) -> list[dict[str, str]]:
    """根据当前输入生成计算前原理预览。"""
    data = _mapping(params)
    project_name = _value(data.get("project_name"), data.get("custom_label"), default="未命名工程")
    section_type = _display_section_type(data.get("section_type"))
    design_flow = _value(data.get("Q"), data.get("design_flow"), default="未提供")
    width = _value(data.get("b"), data.get("channel_width"), default="未提供")
    side_slope = _value(data.get("m"), data.get("side_slope"), default="未提供")
    length = _value(data.get("L"), data.get("chute_length"), default="未提供")
    bed_slope = _value(data.get("i"), data.get("bed_slope"), default="未提供")
    roughness = _value(data.get("n"), data.get("roughness"), default="未提供")
    profile_mode = _display_profile_type(_value(data.get("profile_mode_label"), data.get("profile_mode"), default="未提供"))
    control_mode = _display_control_source(_value(data.get("control_depth_mode_label"), data.get("control_depth_mode"), default="未提供"))
    aeration_coefficient = _value(data.get("aeration_coefficient"), default="未提供")
    freeboard = _value(data.get("sidewall_freeboard_m"), default="未提供")
    pool_factor = _value(data.get("pool_depth_factor"), default="未提供")
    rectification_factor = _value(data.get("outlet_rectification_factor"), default="未提供")
    alpha_profile = _value(data.get("alpha_profile"), data.get("profile_energy_alpha"), data.get("alpha_e"), default="1.1")
    inlet_connection = _display_inlet_connection(_value(data.get("inlet_connection_type_label"), data.get("inlet_connection_type"), default="扭曲面连接"))
    inlet_epsilon = _value(data.get("contraction_coefficient"), default="1.0")
    inlet_head = _value(data.get("inlet_head"), data.get("H0"), default="未提供")

    pending = "计算后生成"
    return [
        _principle(
            "基础断面与水力要素",
            "先把当前输入断面转换为过水面积、湿周、水力半径和水面宽。",
            r"A=(b+mh)h,\quad \chi=b+2h\sqrt{1+m^2},\quad R=\frac{A}{\chi},\quad B=b+2mh",
            "A 为过水面积，χ 为湿周，R 为水力半径，B 为水面宽，b 为底宽，m 为边坡系数，h 为水深。",
            f"工程={project_name}，断面类型={section_type}，Q={design_flow}，b={width}，m={side_slope}",
            pending,
            "完成计算后，会用这些几何关系生成各控制水深对应的断面水力要素。",
            "明渠断面几何关系",
        ),
        _principle(
            "正常水深",
            "用曼宁公式反算当前底坡和糙率下的均匀流水深。",
            r"Q=\frac{1}{n}AR^{2/3}i^{1/2}",
            "Q 为流量，n 为糙率，A 为过水面积，R 为水力半径，i 为渠道底坡。",
            f"Q={design_flow}，n={roughness}，i={bed_slope}",
            pending,
            "计算后会通过试算水深，使公式流量与设计流量一致。",
            "GB 50288-2018 与明渠均匀流理论",
        ),
        _principle(
            "临界水深",
            "求断面比能最小时的水深，用来判断流态分界。",
            r"\frac{\alpha Q^2}{g}=\frac{A_k^3}{B_k}",
            "α 为动能修正系数，g 为重力加速度，临界面积和临界水面宽按临界水深计算。",
            f"Q={design_flow}，断面类型={section_type}",
            pending,
            "计算后会得到临界水深和临界流速。",
            "教材断面比能和临界流理论",
        ),
        _principle(
            "坡型判别",
            "比较实际底坡和临界底坡，判断本工况属于陡坡、缓坡还是临界坡。",
            r"i_k=\left(\frac{nQ}{A_kR_k^{2/3}}\right)^2",
            "临界底坡按临界水深下的过水面积和水力半径反算。",
            f"i={bed_slope}，n={roughness}，Q={design_flow}",
            pending,
            "计算后会把实际底坡与临界底坡进行比较并给出坡型。",
            "教材临界底坡理论",
        ),
        _principle(
            "起点控制水深",
            "确定陡槽水面线从哪个水深开始推算。",
            r"h_s=h_k\quad(\text{自由衔接}),\quad h_s=h_m\quad(\text{人工或实测控制})",
            "h_s 为陡槽起点水深，h_k 为临界水深，h_m 为人工指定或实测控制水深。",
            f"起点控制方式={control_mode}",
            pending,
            "计算后会按自由衔接、人工指定、进口控制或模型试验结果确定起算水深。",
            "入口控制段计算",
        ),
        _principle(
            "入口过流能力",
            "检查入口是否能通过设计流量。",
            r"Q_{\text{过流}}=\varepsilon\mu b_c\sqrt{2g}H_0^{3/2}",
            "Q_过流 为入口过流能力，ε 为侧收缩系数，μ 为流量系数，b_c 为控制断面宽度，H_0 为计入堰前流速水头的堰上总水头。",
            f"Q={design_flow}，b={width}，堰上总水头 H_0={inlet_head}，入口连接形式={inlet_connection}，侧收缩系数={inlet_epsilon}，当前支持矩形跌口或等底宽陡坡入口校核",
            pending,
            "计算后会按 GB 50288-2018 附录 N 根据入口连接形式自动确定流量系数；选择手动输入时采用用户给定系数。当前 H_0 由用户直接输入，本版本不自动由堰前水深和流速水头推导。",
            "GB 50288-2018 附录 N",
        ),
        _principle(
            "水面线逐段计算",
            "沿陡槽长度逐段推算水深、水位、流速和弗劳德数。",
            r"E_s=h+\alpha_e\frac{v^2}{2g},\quad J=\left(\frac{nQ}{AR^{2/3}}\right)^2,\quad \Delta s=\frac{E_{s,j+1}-E_{s,j}}{i-\overline{J}}",
            "E_s 为断面比能，v 为流速，J 为水力坡度，Δs 为相邻试算水深之间的距离。",
            f"L={length}，水面线模式={profile_mode}，水面线动能修正系数={alpha_profile}",
            pending,
            "计算后会形成沿程水面线表和纵断面图。",
            "逐段试算法",
        ),
        _principle(
            "掺气水深与侧墙高度",
            "估算高速水流掺气后的水深，并叠加侧墙安全超高。",
            r"h_b=\left(1+\frac{\zeta v}{100}\right)h,\quad H_{\text{侧墙}}=h_b+\Delta h_{\text{壅水}}+F_b",
            "h_b 为掺气水深，ζ 为掺气系数，H_侧墙 为建议侧墙高度，F_b 为安全超高。",
            f"掺气系数={aeration_coefficient}，安全超高={freeboard}",
            pending,
            "计算后会给出最大掺气水深和建议侧墙高度。",
            "GB 50288-2018 附录 N",
        ),
        _principle(
            "水跃与消力池",
            "估算跃后共轭水深，并判断消力池长度和池深。",
            r"h_c''=\frac{h_c'}{2}\left(\sqrt{1+8Fr_1^2}-1\right),\quad L_d=4.5h_c'',\quad d_d\geq \lambda h_c''-h_{\text{下游}}",
            "h_c' 为跃前水深，h_c'' 为跃后共轭水深，Fr_1 为跃前弗劳德数，L_d 为池长，d_d 为池深。",
            f"池深安全系数={pool_factor}",
            pending,
            "计算后会结合尾水条件判断水跃是否稳定，并给出消力池建议尺寸。",
            "水跃理论",
        ),
        _principle(
            "出口整流段",
            "按出口扩散、跃后水深倍数和最小长度确定连接段。",
            r"L_r\geq L_{\Delta b},\quad L_r\geq \eta h_c'',\quad L_r\geq L_{\text{最小}}",
            "L_r 为出口整流段长度，L_Δb 为宽度渐变所需长度，η 为跃后水深倍数控制系数。",
            f"整流长度系数={rectification_factor}",
            pending,
            "计算后会取各控制条件中的较大值作为出口整流段建议长度。",
            "出口连接段整流布置校核口径",
        ),
        _principle(
            "规范校核与风险提示",
            "把计算结果整理成校核结论和风险提示。",
            r"\text{结论}=\text{逐项校核结果}+\text{风险提示}",
            "校核项目来自纵坡、流速、入口能力、尾水条件等结果。",
            f"Q={design_flow}，L={length}",
            pending,
            "计算后会把需要人工复核的项目列入风险提示。",
            "GB 50288-2018 与工程复核口径",
        ),
    ]
