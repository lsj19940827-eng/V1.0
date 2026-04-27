# -*- coding: utf-8 -*-
"""有压管道水锤验算原理展示窗口。"""

from __future__ import annotations

import html
from typing import Any, Dict, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

try:
    from qfluentwidgets import PushButton
except ImportError:  # pragma: no cover - 兼容无 qfluentwidgets 环境
    from PySide6.QtWidgets import QPushButton as PushButton

from app_渠系计算前端.webview_compat import create_web_view, load_html_content

try:
    from app_渠系计算前端.formula_renderer import render_latex_svg
except Exception:  # pragma: no cover - 依赖环境相关
    render_latex_svg = None


_INLINE_SYMBOL_REPLACEMENTS = (
    ("Hmax", "H<sub>max</sub>"),
    ("Hmin", "H<sub>min</sub>"),
    ("H_allow", "H<sub>allow</sub>"),
    ("μ_s", "μ<sub>s</sub>"),
    ("H0", "H<sub>0</sub>"),
    ("v0", "v<sub>0</sub>"),
    ("Ts", "T<sub>s</sub>"),
    ("ΔH+", "ΔH<sup>+</sup>"),
    ("ΔH-", "ΔH<sup>-</sup>"),
    ("M+", "M<sup>+</sup>"),
    ("M-", "M<sup>-</sup>"),
)


class PressurePipeWaterHammerPrincipleDialog(QDialog):
    """展示当前水锤验算公式、判定流程和可选代入值。"""

    def __init__(
        self,
        parent=None,
        *,
        route_name: str = "",
        segment_name: str = "",
        inputs: Dict[str, Any] | None = None,
        result: Dict[str, Any] | None = None,
        members: List[Dict[str, Any]] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("水锤验算原理")
        self.resize(920, 720)
        self.setMinimumSize(720, 520)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

        self.html = build_water_hammer_principle_html(
            route_name=route_name,
            segment_name=segment_name,
            inputs=inputs or {},
            result=result or {},
            members=members or [],
        )

        layout = QVBoxLayout(self)
        self._view = create_web_view(self)
        load_html_content(self._view, self.html)
        layout.addWidget(self._view, 1)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = PushButton("关闭")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)


def build_water_hammer_principle_html(
    *,
    route_name: str,
    segment_name: str,
    inputs: Dict[str, Any],
    result: Dict[str, Any],
    members: List[Dict[str, Any]] | None = None,
) -> str:
    """构造水锤验算原理 HTML。"""
    body = [
        "<h1>有压管道水锤验算原理</h1>",
        _intro_block(route_name, segment_name),
        _scope_block(),
        _formula_section(
            "1. 水锤波速",
            [
                (
                    r"a=\frac{1425}{\sqrt{1+\frac{K}{E}\frac{D}{t}c_p}}",
                    "按 GB/T 20203-2017 口径计算水锤波传播速度。K 为水体体积弹性模量，E 为管材弹性模量，D 为管径，t 为壁厚，cp 为管材系数。",
                ),
                (
                    r"c_p=1,\qquad c_p=\frac{1}{1+0.95a_0}",
                    "匀质管取 cp=1；钢筋混凝土管、预应力钢筒混凝土管和 PCCP 管有 a0 时按公式计算 cp，未填 a0 时按 cp=1 简化计算并提示。",
                )
            ],
        ),
        _formula_section(
            "2. 水锤相时与基础水头",
            [
                (
                    r"\mu_s=2\sum_i\frac{L_i}{a_i}",
                    "界面中的 μ(s) 表示水锤相时，即水击波往返传播一次所需时间。为避免和手册中的断面系数 μ 混淆，这里记作 μ_s。",
                ),
                (
                    r"H_0=H_{st}-Z_c,\qquad H_{allow}=\frac{P_{allow}}{\rho g}",
                    "H0 为初始压强水头；默认允许压力 1.0 MPa，按 ρ=1000kg/m³、g=9.81m/s² 换算为 101.9368m 工程水头。",
                ),
            ],
        ),
        _formula_section(
            "3. 直接正/负水击",
            [
                (
                    r"\Delta H_d=\frac{a v_0}{g}",
                    "当启闭时间 Ts 不大于水锤相时，按直接水击候选值计算。正水击和负水击都使用这一候选压强幅值。",
                )
            ],
        ),
        _formula_section(
            "4. 缓闭正水击候选",
            [
                (
                    r"H_i=\frac{2Lv_0}{g(T_t+T_s)}",
                    "当 Ts 大于水锤相时，GB/T 20203-2017 式(21)给出间接水击压力 Hi。",
                ),
                (
                    r"\mu=\frac{a v_0}{2gH_0},\qquad \sigma=\frac{L v_0}{gH_0T_s}",
                    "缓闭时先计算断面系数 μ 和系统系数 σ。这里的 μ 是无量纲断面系数，不是界面中的相时 μ(s)。",
                ),
                (
                    r"\tau\sqrt{1+\zeta}=1-\frac{\zeta}{2\mu}",
                    "第一相正水击通过二分法求无量纲压强 ζ。",
                ),
                (
                    r"\zeta_{end}^{+}=\frac{\sigma}{2}\left(\sigma+\sqrt{4+\sigma^2}\right)",
                    "末相正水击按线性关阀末相公式计算。",
                ),
            ],
        ),
        _formula_section(
            "5. 缓开负水击候选",
            [
                (
                    r"\tau\sqrt{1-\zeta}=\frac{\zeta}{2\mu}",
                    "第一相负水击同样通过二分法求无量纲压降 ζ。",
                ),
                (
                    r"\zeta_{end}^{-}=\frac{\sigma}{2}\left(\sqrt{4+\sigma^2}-\sigma\right)",
                    "负末相水击按线性开阀末相公式计算。",
                ),
            ],
        ),
        _formula_section(
            "6. 控制值与全线判定",
            [
                (
                    r"H_{max,i}=H_{st,i}+\Delta H_i^{+},\qquad H_{min,i}=H_{st,i}-\Delta H_i^{-}",
                    "先按图1-3-3判别直接、一相或末相水击，再形成每个采样点的最高、最低压力水头线。",
                ),
                (
                    r"H_{max,i}-\left(Z_{c,i}-\frac{D_i}{2}\right)\le H_{allow}",
                    "承压校核按管底执行，承压余量等于允许压力水头减去管底最大压力水头。",
                ),
                (
                    r"H_{min,i}-\left(Z_{c,i}+\frac{D_i}{2}\right)\ge 0",
                    "负压和不满管风险按管顶执行；直接水击采用保守同幅分布，一相水击采用近似分布，未采用完整特征线法。",
                ),
                (
                    r"\Delta H^{+}=\max(\Delta H_{GB/T}^{+},\Delta H_{linear}^{+})",
                    "正水击仍保留 GB/T 复核与线性启闭双重取大；任一采样点承压或管顶负压不满足即整段不通过。",
                ),
            ],
        ),
        _note_block(),
        _current_values_block(inputs, result, members or []),
    ]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>{_CSS}</style>
</head>
<body>{''.join(body)}</body>
</html>"""


def _intro_block(route_name: str, segment_name: str) -> str:
    """构造标题下方的对象说明。"""
    title = " / ".join(part for part in [route_name, segment_name] if str(part or "").strip())
    if not title:
        title = "当前水锤验算窗口"
    return f'<div class="lead">对象：{html.escape(title)}</div>'


def _scope_block() -> str:
    """构造适用范围说明。"""
    return (
        '<section class="card"><h2>适用范围</h2>'
        "<p>本窗口说明当前程序已经实现的 GB/T 波速、GB/T 正水击复核与线性启闭水锤验算：先判别水击类型，再形成 Hmax/Hmin，最后按管底承压、管顶负压校核。</p>"
        "<p>事故停泵、水锤防护设备、复杂瞬变模拟等不在当前计算范围内。</p>"
        "</section>"
    )


def _formula_section(title: str, formulas: List[Tuple[str, str]]) -> str:
    """构造一组公式卡片。"""
    parts = [f'<section class="card"><h2>{html.escape(title)}</h2>']
    for latex, description in formulas:
        parts.append('<div class="formula-row">')
        parts.append(f'<div class="formula">{_render_formula(latex)}</div>')
        parts.append(f"<p>{_render_inline_symbols(description)}</p>")
        parts.append("</div>")
    parts.append("</section>")
    return "".join(parts)


def _note_block() -> str:
    """构造图形对照和插值说明。"""
    return (
        '<section class="card"><h2>图1-3-3对照与采样</h2>'
        "<p>图1-3-3 用于判别直接水击、一相水击和末相水击；直接水击和一相水击沿线分布为工程近似，不是完整特征线法。</p>"
        "<p>整线分布验算以 5m 为基础步长，同时保留起终点、管段分界点、纵断面折点和表3水位点，避免漏掉关键位置。</p>"
        "</section>"
    )


def _current_values_block(inputs: Dict[str, Any], result: Dict[str, Any], members: List[Dict[str, Any]]) -> str:
    """构造控制采样点代入值。"""
    details = result.get("details", []) if isinstance(result, dict) else []
    if not details:
        return (
            '<section class="card muted"><h2>控制采样点代入值</h2>'
            "<p>先验算后可看到控制采样点代入值。</p>"
            "</section>"
        )

    critical = result.get("critical_point", {}) if isinstance(result.get("critical_point", {}), dict) else {}
    member_info = _member_info_for_key(members, critical.get("member_key"))
    h0 = critical.get("initial_pressure_head_m", inputs.get("initial_head_m"))
    positive_delta = result.get("positive_delta_h")
    negative_delta = result.get("negative_delta_h")
    hmax = critical.get("hmax_m", result.get("hmax"))
    hmin = critical.get("hmin_m", result.get("hmin"))
    rows = [
        ("所属成员", member_info.get("label", critical.get("member_key", "")), ""),
        ("桩号", critical.get("station_m"), "m"),
        ("D", critical.get("diameter_m", member_info.get("diameter_m")), "m"),
        ("E", member_info.get("elastic_modulus_pa"), "N/m²"),
        ("v0", critical.get("velocity_mps", member_info.get("velocity_mps")), "m/s"),
        ("e", inputs.get("wall_thickness_m"), "m"),
        ("Ts", inputs.get("closing_time_s"), "s"),
        ("允许压力", inputs.get("allowable_pressure_mpa", result.get("allowable_pressure_mpa")), "MPa"),
        ("允许压力水头", result.get("pressure_allow_head_m"), "m"),
        ("H0", h0, "m"),
        ("a", critical.get("a", result.get("a")), "m/s"),
        ("cp", critical.get("pipe_coefficient_cp", result.get("pipe_coefficient_cp")), ""),
        ("a0", critical.get("reinforcement_ratio_a0", result.get("reinforcement_ratio_a0")), ""),
        ("μ(s)", result.get("mu"), "s"),
        ("GB/T ΔH+", result.get("gbt_positive_delta_h"), "m"),
        ("线性启闭 ΔH+", result.get("linear_positive_delta_h"), "m"),
        ("ΔH+", positive_delta, "m"),
        ("控制来源", result.get("positive_governing_method"), ""),
        ("ΔH-", negative_delta, "m"),
        ("Hmax", hmax, "m"),
        ("Hmin", hmin, "m"),
        ("管底最大压力水头", critical.get("pressure_head_max_m"), "m"),
        ("承压余量", result.get("min_margin_m"), "m"),
        ("管顶最低压力水头", critical.get("top_min_pressure_head_m"), "m"),
        ("管顶最低余量", result.get("min_negative_margin_m"), "m"),
    ]
    cells = "".join(
        f"<tr><th>{_render_inline_symbols(label)}</th><td>{html.escape(_fmt(value))}</td><td>{html.escape(unit)}</td></tr>"
        for label, value, unit in rows
    )
    note = f"<p>{_render_inline_symbols('e、Ts 和允许压力为整线统一输入；μ(s) 为整线相时。')}</p>"
    return f'<section class="card"><h2>控制采样点代入值</h2>{note}<table>{cells}</table></section>'


def _member_info_for_key(members: List[Dict[str, Any]], member_key: Any) -> Dict[str, Any]:
    """按成员 key 查找原始参数。"""
    target = str(member_key or "")
    for member in members or []:
        if not isinstance(member, dict):
            continue
        if str(member.get("key", "") or "") == target:
            return member
    return {}


def _render_inline_symbols(text: str) -> str:
    """把说明文字中的常见变量标记转为 HTML 上下标。"""
    rendered = html.escape(str(text))
    for token, replacement in _INLINE_SYMBOL_REPLACEMENTS:
        rendered = rendered.replace(html.escape(token), replacement)
    return rendered


def _render_formula(latex: str) -> str:
    """把 LaTeX 渲染为离线 SVG，失败时退回源码显示。"""
    if render_latex_svg is None:
        return f"<span>{html.escape(latex)}</span>"
    try:
        rendered = render_latex_svg(latex, fontsize=18)
        if rendered:
            return rendered
        return f"<span>{html.escape(latex)}</span>"
    except Exception:
        return f"<span>{html.escape(latex)}</span>"


def _fmt(value: Any) -> str:
    """格式化代入示例数值。"""
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):.6g}"
    except (TypeError, ValueError):
        return str(value)


def _add_or_blank(left: Any, right: Any):
    """安全计算加法。"""
    try:
        return float(left) + float(right)
    except (TypeError, ValueError):
        return None


def _sub_or_blank(left: Any, right: Any):
    """安全计算减法。"""
    try:
        return float(left) - float(right)
    except (TypeError, ValueError):
        return None


_CSS = """
body {
    margin: 0;
    padding: 22px 26px;
    color: #1f2933;
    background: #f5f7fa;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    line-height: 1.65;
}
h1 {
    margin: 0 0 8px;
    color: #0f62a8;
    font-size: 24px;
}
.lead {
    margin: 0 0 16px;
    color: #536471;
    font-size: 14px;
}
.card {
    margin: 12px 0;
    padding: 16px 18px;
    border: 1px solid #d9e3ec;
    border-radius: 8px;
    background: #ffffff;
}
.card h2 {
    margin: 0 0 10px;
    color: #174a7c;
    font-size: 17px;
}
.card p {
    margin: 6px 0;
}
.muted {
    background: #fbfcfe;
    color: #607080;
}
.formula-row {
    margin: 10px 0 14px;
    padding: 12px;
    border-left: 4px solid #2b7dbc;
    background: #f8fbff;
}
.formula {
    overflow-x: auto;
    padding: 4px 0;
}
table {
    width: 100%;
    border-collapse: collapse;
}
th, td {
    border: 1px solid #d8e1ea;
    padding: 8px 10px;
    text-align: left;
}
th {
    width: 120px;
    background: #eef5fb;
}
"""
