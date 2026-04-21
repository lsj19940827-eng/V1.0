# -*- coding: utf-8 -*-
"""加大流量输入模式的共享换算与文案工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


INCREASE_MODE_PERCENT = "percent"
INCREASE_MODE_Q_INCREASED = "q_increased"
INCREASE_PERCENT_DISPLAY_DECIMALS = 3
INCREASE_FORMULA_DISPLAY_DECIMALS = 5
FLOW_VALUE_DISPLAY_DECIMALS = 3


@dataclass
class IncreaseInputResolution:
    """归一化后的加大流量输入结果。"""

    mode: str
    manual_increase_percent: Optional[float]
    engine_increase_percent: float
    q_increased_value: Optional[float]


def normalize_increase_mode(mode: Optional[str]) -> str:
    """规范化输入模式，旧数据默认回退到按比例。"""
    return INCREASE_MODE_Q_INCREASED if mode == INCREASE_MODE_Q_INCREASED else INCREASE_MODE_PERCENT


def get_auto_increase_percent(design_q: float) -> float:
    """按现有规范查表获取默认加大比例。"""
    if design_q <= 0:
        return 0.0
    if design_q < 1:
        return 30.0
    if design_q < 5:
        return 25.0
    if design_q < 20:
        return 20.0
    if design_q < 50:
        return 15.0
    if design_q < 100:
        return 10.0
    if design_q <= 300:
        return 5.0
    return 5.0


def calculate_q_increased(design_q: float, increase_percent: float) -> float:
    """按比例换算加大后流量。"""
    return design_q * (1.0 + increase_percent / 100.0)


def calculate_increase_percent_from_q(design_q: float, q_increased: float) -> float:
    """按Q加大反算比例。"""
    if design_q <= 0:
        raise ValueError("设计流量 Q 必须大于 0")
    if q_increased <= design_q:
        raise ValueError("加大流量 Q加大必须大于设计流量 Q")
    return round((q_increased / design_q - 1.0) * 100.0, 10)


def _parse_float(text: str, label: str) -> float:
    """把文本解析成数字，并统一报错口径。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError(f"请输入{label}")
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{label}输入无效") from exc


def _coerce_float(value, default: float = 0.0) -> float:
    """把结果或缓存里的数值稳妥转成 float。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_increase_percent(percent: float) -> str:
    """按统一规则格式化加大比例百分比。"""
    return f"{_coerce_float(percent):.{INCREASE_PERCENT_DISPLAY_DECIMALS}f}%"


def format_increase_ratio(percent: float) -> str:
    """按统一规则格式化公式中的比例小数。"""
    ratio = _coerce_float(percent) / 100.0
    return f"{ratio:.{INCREASE_FORMULA_DISPLAY_DECIMALS}f}"


def format_increase_multiplier(percent: float) -> str:
    """按统一规则格式化公式中的倍率。"""
    multiplier = 1.0 + _coerce_float(percent) / 100.0
    return f"{multiplier:.{INCREASE_FORMULA_DISPLAY_DECIMALS}f}"


def format_q_increased_value(q_increased: float) -> str:
    """按统一规则格式化 Q加大 数值显示。"""
    return f"{_coerce_float(q_increased):.{FLOW_VALUE_DISPLAY_DECIMALS}f} m³/s"


def build_increase_formula_lines(
    *,
    design_q: float,
    increase_percent: float,
    q_increased: float,
) -> tuple[str, str, str]:
    """生成结果区共用的加大流量公式代入行。"""
    return (
        f"Q加大 = Q × (1 + {format_increase_ratio(increase_percent)})",
        f"= {_coerce_float(design_q):.{FLOW_VALUE_DISPLAY_DECIMALS}f} × {format_increase_multiplier(increase_percent)}",
        f"= {format_q_increased_value(q_increased)}",
    )


def resolve_increase_input(
    *,
    use_increase: bool,
    mode: Optional[str],
    design_q: float,
    percent_text: str,
    q_increased_text: str,
    disabled_percent: Optional[float] = 0.0,
) -> IncreaseInputResolution:
    """把界面输入统一归一为内核继续使用的比例口径。"""
    normalized_mode = normalize_increase_mode(mode)
    if not use_increase:
        return IncreaseInputResolution(
            mode=normalized_mode,
            manual_increase_percent=disabled_percent,
            engine_increase_percent=_coerce_float(disabled_percent),
            q_increased_value=design_q,
        )

    if normalized_mode == INCREASE_MODE_Q_INCREASED:
        q_increased = _parse_float(q_increased_text, "加大流量 Q加大")
        percent = calculate_increase_percent_from_q(design_q, q_increased)
        return IncreaseInputResolution(
            mode=normalized_mode,
            manual_increase_percent=percent,
            engine_increase_percent=percent,
            q_increased_value=q_increased,
        )

    raw_percent = (percent_text or "").strip()
    if not raw_percent:
        auto_percent = get_auto_increase_percent(design_q)
        return IncreaseInputResolution(
            mode=normalized_mode,
            manual_increase_percent=None,
            engine_increase_percent=auto_percent,
            q_increased_value=calculate_q_increased(design_q, auto_percent),
        )
    percent = _parse_float(raw_percent, "流量加大比例")
    return IncreaseInputResolution(
        mode=normalized_mode,
        manual_increase_percent=percent,
        engine_increase_percent=percent,
        q_increased_value=calculate_q_increased(design_q, percent),
    )


def build_increase_hint_text(
    *,
    use_increase: bool,
    mode: Optional[str],
    design_q_text: str,
    percent_text: str,
    q_increased_text: str,
) -> str:
    """生成输入区灰色提示文案。"""
    if not use_increase:
        return ""

    normalized_mode = normalize_increase_mode(mode)
    raw_q = (design_q_text or "").strip()
    if not raw_q:
        return "请输入设计流量 Q 后再换算"
    try:
        design_q = float(raw_q)
    except ValueError:
        return "设计流量 Q 输入无效"
    if design_q <= 0:
        return "设计流量 Q 必须大于 0"

    if normalized_mode == INCREASE_MODE_Q_INCREASED:
        raw_q_inc = (q_increased_text or "").strip()
        if not raw_q_inc:
            return "请输入加大流量 Q加大，且需大于设计流量 Q"
        try:
            q_increased = float(raw_q_inc)
        except ValueError:
            return "加大流量 Q加大 输入无效"
        if q_increased <= design_q:
            return "加大流量 Q加大必须大于设计流量 Q"
        percent = calculate_increase_percent_from_q(design_q, q_increased)
        return f"系统换算：流量加大比例 = {format_increase_percent(percent)}"

    raw_percent = (percent_text or "").strip()
    if not raw_percent:
        auto_percent = get_auto_increase_percent(design_q)
        auto_q = calculate_q_increased(design_q, auto_percent)
        return f"留空将按规范自动取 {format_increase_percent(auto_percent)} ，Q加大 = {format_q_increased_value(auto_q)}"
    try:
        percent = float(raw_percent)
    except ValueError:
        return "流量加大比例输入无效"
    q_increased = calculate_q_increased(design_q, percent)
    return f"系统换算：Q加大 = {format_q_increased_value(q_increased)}"


def build_increase_summary_lines(
    *,
    use_increase: bool,
    mode: Optional[str],
    percent_text: str,
    q_increased_text: str,
    result_increase_percent: float,
    result_q_increased: float,
) -> tuple[str, str, str]:
    """生成结果、TXT、Word、DXF共用的输入说明。"""
    result_increase_percent = _coerce_float(result_increase_percent, 0.0)
    result_q_increased = _coerce_float(result_q_increased, 0.0)

    if not use_increase:
        return (
            "输入方式 = 未启用加大流量",
            "用户输入 = 未启用",
            "系统换算 = 无",
        )

    normalized_mode = normalize_increase_mode(mode)
    raw_percent = (percent_text or "").strip()
    raw_q = (q_increased_text or "").strip()

    if normalized_mode == INCREASE_MODE_Q_INCREASED:
        user_value = raw_q
        if user_value:
            try:
                user_value = format_q_increased_value(float(user_value))
            except ValueError:
                user_value = f"{user_value} m³/s"
        else:
            user_value = format_q_increased_value(result_q_increased)
        return (
            "输入方式 = 按Q加大",
            f"用户输入 = Q加大 = {user_value}",
            f"系统换算 = 流量加大比例 = {format_increase_percent(result_increase_percent)}",
        )

    if raw_percent:
        try:
            user_percent = format_increase_percent(float(raw_percent))
        except ValueError:
            user_percent = f"{raw_percent}%"
        return (
            "输入方式 = 按比例",
            f"用户输入 = 流量加大比例 = {user_percent}",
            f"系统换算 = Q加大 = {format_q_increased_value(result_q_increased)}",
        )

    return (
        "输入方式 = 按比例（自动查表）",
        "用户输入 = 未填写，按规范自动查表",
        f"系统换算 = 流量加大比例 = {format_increase_percent(result_increase_percent)} ，Q加大 = {format_q_increased_value(result_q_increased)}",
    )
