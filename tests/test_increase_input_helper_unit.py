# -*- coding: utf-8 -*-
"""加大流量输入 helper 的换算与校验测试。"""

import pytest

from app_渠系计算前端.increase_input_helper import (
    INCREASE_MODE_PERCENT,
    INCREASE_MODE_Q_INCREASED,
    build_increase_formula_lines,
    build_increase_hint_text,
    build_increase_summary_lines,
    get_auto_increase_percent,
    resolve_increase_input,
)


def test_percent_mode_blank_keeps_auto_lookup_rule():
    result = resolve_increase_input(
        use_increase=True,
        mode=INCREASE_MODE_PERCENT,
        design_q=5.0,
        percent_text="",
        q_increased_text="",
        disabled_percent=0.0,
    )

    assert result.manual_increase_percent is None
    assert get_auto_increase_percent(5.0) == pytest.approx(20.0)
    assert result.q_increased_value == pytest.approx(6.0)


def test_percent_mode_blank_keeps_user_empty_and_exposes_engine_percent():
    result = resolve_increase_input(
        use_increase=True,
        mode=INCREASE_MODE_PERCENT,
        design_q=0.51,
        percent_text="",
        q_increased_text="",
        disabled_percent=0.0,
    )

    assert result.manual_increase_percent is None
    assert result.engine_increase_percent == pytest.approx(30.0)
    assert result.q_increased_value == pytest.approx(0.663)


def test_q_increased_mode_converts_total_flow_back_to_percent():
    result = resolve_increase_input(
        use_increase=True,
        mode=INCREASE_MODE_Q_INCREASED,
        design_q=5.0,
        percent_text="",
        q_increased_text="5.5",
        disabled_percent=0.0,
    )

    assert result.manual_increase_percent == pytest.approx(10.0)
    assert result.q_increased_value == pytest.approx(5.5)


def test_q_increased_mode_rejects_value_not_greater_than_design_q():
    with pytest.raises(ValueError, match="Q加大必须大于设计流量 Q"):
        resolve_increase_input(
            use_increase=True,
            mode=INCREASE_MODE_Q_INCREASED,
            design_q=5.0,
            percent_text="",
            q_increased_text="5.0",
            disabled_percent=0.0,
        )


def test_summary_lines_show_mode_user_input_and_system_conversion():
    lines = build_increase_summary_lines(
        use_increase=True,
        mode=INCREASE_MODE_Q_INCREASED,
        percent_text="",
        q_increased_text="5.5",
        result_increase_percent=10.0,
        result_q_increased=5.5,
    )

    assert lines == (
        "输入方式 = 按Q加大",
        "用户输入 = Q加大 = 5.500 m³/s",
        "系统换算 = 流量加大比例 = 10.000%",
    )


def test_q_increased_mode_keeps_full_precision_for_downstream_calculation():
    result = resolve_increase_input(
        use_increase=True,
        mode=INCREASE_MODE_Q_INCREASED,
        design_q=5.0,
        percent_text="",
        q_increased_text="5.91234",
        disabled_percent=0.0,
    )

    assert result.manual_increase_percent == pytest.approx(18.2468)
    assert result.q_increased_value == pytest.approx(5.91234)


def test_hint_text_shows_three_decimal_percent_for_q_increased_mode():
    hint = build_increase_hint_text(
        use_increase=True,
        mode=INCREASE_MODE_Q_INCREASED,
        design_q_text="5.0",
        percent_text="",
        q_increased_text="5.91",
    )

    assert hint == "系统换算：流量加大比例 = 18.200%"


def test_summary_lines_show_three_decimal_percent_for_q_increased_mode():
    lines = build_increase_summary_lines(
        use_increase=True,
        mode=INCREASE_MODE_Q_INCREASED,
        percent_text="",
        q_increased_text="5.91",
        result_increase_percent=18.2,
        result_q_increased=5.91,
    )

    assert lines == (
        "输入方式 = 按Q加大",
        "用户输入 = Q加大 = 5.910 m³/s",
        "系统换算 = 流量加大比例 = 18.200%",
    )


def test_formula_lines_show_five_decimal_ratio_and_multiplier():
    lines = build_increase_formula_lines(
        design_q=5.0,
        increase_percent=18.2,
        q_increased=5.91,
    )

    assert lines == (
        "Q加大 = Q × (1 + 0.18200)",
        "= 5.000 × 1.18200",
        "= 5.910 m³/s",
    )
