# -*- coding: utf-8 -*-
"""泄水渠与陡坡第二版规划行为的红灯单元测试。"""

import importlib
from collections.abc import Mapping, Sequence

import pytest


def _core_module():
    """载入泄水渠与陡坡计算内核。"""
    return importlib.import_module("calc_渠系计算算法内核.泄水渠与陡坡设计")


def _base_rectangular_case(**extra):
    """构造矩形陡槽基础工况。"""
    data = {
        "section_type": "rectangular",
        "Q": 10.0,
        "b": 2.0,
        "m": 0.0,
        "i": 0.01,
        "n": 0.014,
        "L": 30.0,
        "profile_mode": "END_DEPTH_BY_LENGTH",
        "depth_step": 0.02,
    }
    data.update(extra)
    return data


def _base_trapezoidal_case(**extra):
    """构造熊启钧棱柱体陡坡基础工况。"""
    data = {
        "section_type": "trapezoidal",
        "Q": 20.0,
        "b": 1.0,
        "m": 1.5,
        "i": 0.02,
        "n": 0.014,
        "L": 80.0,
        "profile_mode": "END_DEPTH_BY_LENGTH",
        "depth_step": 0.02,
    }
    data.update(extra)
    return data


def _all_text(value):
    """递归收集结果中的文字，便于断言中文说明。"""
    texts = []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        for item in value.values():
            texts.extend(_all_text(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            texts.extend(_all_text(item))
    return texts


def _has_text(result, *needles):
    """判断结果文字中是否包含全部关键词。"""
    combined = "\n".join(_all_text(result))
    return all(needle in combined for needle in needles)


def _patch_multi_flow_hydraulic_chain(monkeypatch, core, peak_q: float) -> None:
    """用可控指标替代重水力链路，专门验证多流量细化选点。"""
    monkeypatch.setattr(core, "calculate_depth_for_flow", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(core, "_solve_critical_depth", lambda *_args, **_kwargs: 0.8)
    monkeypatch.setattr(core, "_critical_slope", lambda *_args, **_kwargs: 0.01)
    monkeypatch.setattr(core, "_build_hydraulic_summary", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(core, "_resolve_start_control", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(core, "_profile_result", lambda *_args, **_kwargs: {})

    def fake_jump(_data, local_params, _hydraulic, _profile):
        """让控制指标在指定流量附近取最大值。"""
        q_value = float(local_params["Q"])
        metric = 100.0 - abs(q_value - peak_q)
        return {
            "pre_jump_depth_m": 0.4,
            "conjugate_depth_m": 1.4,
            "control_depth_m": 0.6,
            "control_depth_difference_m": metric,
            "positive_control_deficit_m": max(0.0, metric),
            "tailwater_deficit_m": 0.0,
            "recommended_pool_length_m": 4.0,
            "recommended_pool_depth_m": 1.0,
            "recommended_transition_length_m": 8.0,
        }

    monkeypatch.setattr(core, "_hydraulic_jump_result", fake_jump)


def _profile_type(result):
    """从兼容字段读取水面线型。"""
    profile = result.get("profile", {})
    hydraulic = result.get("hydraulic", {})
    return (
        profile.get("water_profile_type")
        or profile.get("profile_type")
        or profile.get("line_type")
        or hydraulic.get("water_profile_type")
        or result.get("water_profile_type")
    )


def _first_profile_point(result):
    """读取第一个沿程点。"""
    points = result.get("profile_points") or result.get("profile", {}).get("points") or []
    assert points, "应返回可用于检查起点的沿程点"
    return points[0]


def _patch_multi_flow_hydraulic_chain(monkeypatch, core, peak_q):
    """把多流量控制依赖的水力链路替换为可预测曲线。"""
    monkeypatch.setattr(core, "calculate_depth_for_flow", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(core, "_solve_critical_depth", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(core, "_critical_slope", lambda *_args, **_kwargs: 0.01)
    monkeypatch.setattr(
        core,
        "_build_hydraulic_summary",
        lambda section_type, *_args, **_kwargs: {
            "section_type": section_type,
            "normal_depth_m": 1.0,
            "critical_depth_m": 1.0,
            "slope_type": "steep",
        },
    )
    monkeypatch.setattr(core, "_resolve_start_control", lambda *_args, **_kwargs: {"source": "critical_depth", "depth_m": 1.0})
    monkeypatch.setattr(core, "_profile_result", lambda *_args, **_kwargs: {"available": True, "end_depth_m": 1.0})

    def fake_jump(_data, local_params, _hydraulic, _profile):
        """让控制指标在 peak_q 附近达到最大。"""
        q_value = float(local_params["Q"])
        control_metric = round(100.0 - (q_value - peak_q) ** 2, 6)
        return {
            "pre_jump_depth_m": 1.0,
            "conjugate_depth_m": 2.0,
            "control_depth_m": 1.5,
            "control_depth_difference_m": control_metric,
            "positive_control_deficit_m": max(0.0, control_metric),
            "tailwater_deficit_m": 0.0,
            "recommended_pool_length_m": round(q_value, 6),
            "recommended_pool_depth_m": round(q_value / 10.0, 6),
            "recommended_transition_length_m": 5.0,
        }

    monkeypatch.setattr(core, "_hydraulic_jump_result", fake_jump)


def test_profile_type_identifies_steep_b2_and_mild_upstream_b1_control():
    """水面线型应说明标准陡坡为 b_2，缓坡上游末端控制为 b_1。"""
    core = _core_module()

    steep = core.quick_calculate_spillway_steep_chute(_base_rectangular_case())
    mild = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(
            i=0.0001,
            upstream_control_depth=2.4,
            profile_mode="UPSTREAM_END_CONTROL",
        )
    )

    assert steep["success"] is True
    assert _profile_type(steep) == "b_2"
    assert _has_text(steep, "陡坡", "b_2")
    assert mild["success"] is True
    assert _profile_type(mild) == "b_1"
    assert _has_text(mild, "缓坡", "上游", "b_1")


def test_mild_upstream_free_connection_uses_critical_depth_not_upstream_normal_depth():
    """上游缓坡自由接陡坡时，应默认从临界水深起算并记录衔接说明。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(
            upstream_channel_slope_type="mild",
            upstream_connection_mode="free_to_steep",
            upstream_normal_depth=2.6,
        )
    )

    first_point = _first_profile_point(result)
    critical_depth = result["hydraulic"]["critical_depth_m"]
    connection = result.get("upstream_connection") or result.get("profile", {}).get("upstream_connection")

    assert result["success"] is True
    assert first_point["depth_m"] == pytest.approx(critical_depth, abs=0.03)
    assert first_point["depth_m"] != pytest.approx(2.6, abs=0.03)
    assert connection
    assert connection.get("start_depth_source") == "critical_depth"
    assert _has_text(connection, "上游缓坡", "正常水深", "临界水深")


def test_manual_or_actual_control_depth_overrides_start_depth_and_records_source():
    """人工或实际控制水深应作为陡槽起点水深，并记录来源。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(
            control_depth_mode="manual",
            manual_start_depth=2.1,
            upstream_normal_depth=2.6,
        )
    )

    first_point = _first_profile_point(result)
    start_control = result.get("start_control") or result.get("profile", {}).get("start_control") or {}

    assert result["success"] is True
    assert first_point["depth_m"] == pytest.approx(2.1, abs=0.01)
    assert start_control
    assert start_control.get("depth_m") == pytest.approx(2.1, abs=0.01)
    assert _has_text(start_control, "人工", "控制水深")


def test_two_depth_mode_uses_explicit_start_depth_even_when_above_critical():
    """已知两端水深模式应使用用户输入的起点水深，而不是强制改成临界水深。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_trapezoidal_case(
            profile_mode="LENGTH_BY_TWO_DEPTHS",
            start_depth=2.1,
            end_depth=1.5,
        )
    )

    first_point = _first_profile_point(result)
    assert result["success"] is True
    assert first_point["depth_m"] == pytest.approx(2.1, abs=0.01)
    assert first_point["depth_m"] != pytest.approx(result["hydraulic"]["critical_depth_m"], abs=0.01)


def test_reverse_depth_profile_does_not_fake_success():
    """终点水深高于起点水深时，不应返回长度为 0 的假成功水面线。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(
            profile_mode="LENGTH_BY_TWO_DEPTHS",
            control_depth_mode="manual",
            manual_start_depth=0.5,
            end_depth=1.0,
        )
    )

    profile = result.get("profile") or {}
    assert result["success"] is True
    assert profile.get("available") is False
    assert profile.get("points") == []
    assert _has_text(result, "起点水深", "目标水深", "不能")


def test_subcritical_or_failed_profile_does_not_report_hydraulic_jump_design():
    """水面线不可用或出口不是急流时，不应输出水跃和消力池设计尺寸。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(
            control_depth_mode="manual",
            manual_start_depth=2.1,
        )
    )

    jump = result.get("hydraulic_jump") or {}
    assert result["success"] is True
    assert result["profile"]["available"] is False
    assert jump["applicable"] is False
    assert jump["status"] in {"profile_unavailable", "not_supercritical"}
    assert jump["recommended_pool_length_m"] is None
    assert jump["recommended_pool_depth_m"] is None
    assert "跃后共轭水深" not in result["summary"]
    assert "建议消力池长度" not in result["summary"]


def test_actual_control_does_not_report_upstream_b1_as_start_source():
    """人工或实际控制时，上游衔接不应误报为自由临界控制的 b_1。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(
            control_depth_mode="manual",
            manual_start_depth=2.1,
            upstream_normal_depth=2.6,
        )
    )

    connection = result.get("upstream_connection") or {}
    assert result["success"] is True
    assert result["start_control"]["mode"] == "manual"
    assert connection.get("water_profile_type") in {None, ""}
    assert _has_text(connection, "人工", "上游正常水深")


def test_inlet_and_model_control_depth_modes_read_their_own_depth_fields():
    """进口控制和模型试验应读取各自字段，不依赖人工水深字段。"""
    core = _core_module()

    inlet = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(control_depth_mode="inlet_control", inlet_control_depth=0.8)
    )
    model = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(control_depth_mode="model_test", model_test_start_depth=0.9)
    )

    assert inlet["start_control"]["mode"] == "inlet_control"
    assert inlet["start_control"]["depth_m"] == pytest.approx(0.8, abs=0.01)
    assert model["start_control"]["mode"] == "model_test"
    assert model["start_control"]["depth_m"] == pytest.approx(0.9, abs=0.01)


def test_rectangular_downstream_hydraulic_jump_and_stilling_pool_are_reported():
    """矩形断面应计算水跃、尾水判断和消力池建议尺寸。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(
            Q=12.0,
            b=3.0,
            i=0.03,
            L=45.0,
            downstream_tailwater_depth=0.9,
        )
    )

    jump = result.get("hydraulic_jump") or result.get("downstream_energy_dissipation")

    assert result["success"] is True
    assert jump
    assert jump["pre_jump_depth_m"] > 0
    assert jump["conjugate_depth_m"] > jump["pre_jump_depth_m"]
    assert jump["tailwater_depth_m"] == pytest.approx(0.9, abs=0.01)
    assert jump["tailwater_judgement"] in {"尾水不足", "尾水适宜", "尾水过高"}
    assert jump["recommended_pool_length_m"] > 0
    assert jump["recommended_pool_depth_m"] >= 0
    assert jump["recommended_transition_length_m"] > 0
    assert jump["outlet_rectification"]["recommended_length_m"] == pytest.approx(jump["recommended_transition_length_m"])
    assert _has_text(jump, "水跃", "消力池")


def test_aerated_depth_and_sidewall_top_are_added_to_points_and_summary():
    """沿程点和汇总应包含掺气水深、掺气水位和侧墙顶高程。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_trapezoidal_case(
            Q=28.0,
            i=0.05,
            L=60.0,
            sidewall_freeboard_m=0.5,
        )
    )

    points = result.get("profile_points") or []
    aeration = result.get("aeration_and_sidewall") or result.get("summary", {})

    assert result["success"] is True
    assert len(points) >= 2
    assert all("aerated_depth_m" in point for point in points)
    assert all("aerated_water_elevation_m" in point for point in points)
    assert all("sidewall_top_elevation_m" in point for point in points)
    assert aeration["max_aerated_depth_m"] >= max(point["aerated_depth_m"] for point in points)
    assert aeration["recommended_sidewall_height_m"] > aeration["max_aerated_depth_m"]
    assert _has_text(aeration, "掺气", "侧墙")


def test_multi_flow_control_selects_flow_with_largest_control_requirement():
    """分级流量应返回多流量控制结果，并选出控制量最大的流量。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(
            Q=10.0,
            flow_cases=[
                {"name": "低流量", "Q": 6.0},
                {"name": "设计流量", "Q": 10.0},
                {"name": "校核流量", "Q": 16.0},
            ],
            downstream_tailwater_depth=0.9,
            sidewall_freeboard_m=0.5,
        )
    )

    multi = result.get("multi_flow_control")

    assert result["success"] is True
    assert multi
    assert len(multi["cases"]) == 3
    assert multi["control_flow_m3s"] in {6.0, 10.0, 16.0}
    metric = multi["control_metric"]
    control_case = multi["control_case"]
    assert control_case["Q"] == pytest.approx(multi["control_flow_m3s"])
    assert control_case[metric] == max(case[metric] for case in multi["cases"])
    assert _has_text(multi, "控制流量")


def test_multi_flow_control_does_not_default_to_first_flow_when_depth_deficits_tie():
    """控制差值相同时，应继续用池长、池深和流量作稳定判别，不退化为第一条。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(
            Q=10.0,
            flow_cases=[
                {"name": "低流量", "Q": 6.0},
                {"name": "设计流量", "Q": 10.0},
                {"name": "校核流量", "Q": 16.0},
            ],
            downstream_tailwater_depth=20.0,
        )
    )

    multi = result.get("multi_flow_control")
    assert multi["control_flow_m3s"] == pytest.approx(16.0)
    assert multi["control_case"]["name"] == "校核流量"


def test_multi_flow_control_refines_control_interval_and_reselects_final_flow(monkeypatch):
    """自动细化应在初筛控制点邻近区间按1%设计流量加密，并用合并工况重选控制流量。"""
    core = _core_module()
    _patch_multi_flow_hydraulic_chain(monkeypatch, core, peak_q=11.3)
    initial_cases = [{"name": f"{step * 10}%设计流量", "Q": step * 2.0} for step in range(1, 11)]

    multi = core._multi_flow_control(
        {
            "section_type": "rectangular",
            "flow_cases": initial_cases,
            "flow_case_refinement": {"enabled": True, "coarse_step_ratio": 0.10, "refine_step_ratio": 0.01},
        },
        {"Q": 20.0, "b": 1.0, "m": 0.0, "i": 0.02, "n": 0.014},
    )

    q_values = [case["Q"] for case in multi["cases"]]
    refined_values = [round(10.0 + idx * 0.2, 6) for idx in range(21)]

    assert len(multi["cases"]) > len(initial_cases)
    assert {10.0, 12.0, 14.0}.issubset(q_values)
    assert all(value in q_values for value in refined_values)
    assert len(q_values) == len(set(q_values))
    assert multi["control_flow_m3s"] == pytest.approx(11.4)
    assert multi["control_flow_m3s"] not in {case["Q"] for case in initial_cases}
    assert multi["refinement"]["interval_start_flow_m3s"] == pytest.approx(10.0)
    assert multi["refinement"]["interval_end_flow_m3s"] == pytest.approx(14.0)
    assert multi["refinement"]["coarse_step_ratio"] == pytest.approx(0.10)
    assert multi["refinement"]["refine_step_ratio"] == pytest.approx(0.01)
    assert multi["refinement"]["refine_step_flow_m3s"] == pytest.approx(0.2)
    assert multi["refinement"]["initial_control_flow_m3s"] == pytest.approx(12.0)
    assert multi["refinement"]["added_case_count"] > 0
    assert multi["refinement"]["candidate_case_count"] == len(multi["cases"])
    assert _has_text(multi, "初筛", "自动加密")


def test_multi_flow_control_refines_between_design_and_increased_flow(monkeypatch):
    """加大流量为初筛边界控制点时，应加密设计流量到加大流量之间的区间。"""
    core = _core_module()
    _patch_multi_flow_hydraulic_chain(monkeypatch, core, peak_q=22.0)
    initial_cases = [{"name": f"{step * 10}%设计流量", "Q": step * 2.0} for step in range(1, 11)]
    initial_cases.append({"name": "加大流量", "Q": 23.0})

    multi = core._multi_flow_control(
        {
            "section_type": "rectangular",
            "flow_cases": initial_cases,
            "flow_case_refinement": {"enabled": True, "coarse_step_ratio": 0.10, "refine_step_ratio": 0.01},
        },
        {"Q": 20.0, "b": 1.0, "m": 0.0, "i": 0.02, "n": 0.014},
    )

    q_values = [case["Q"] for case in multi["cases"]]

    assert 22.0 in q_values
    assert multi["control_flow_m3s"] == pytest.approx(22.0)
    assert multi["control_case"]["name"].startswith("自动细化流量")
    assert multi["refinement"]["interval_start_flow_m3s"] == pytest.approx(20.0)
    assert multi["refinement"]["interval_end_flow_m3s"] == pytest.approx(23.0)
    assert len(q_values) == len(set(q_values))


def test_lightweight_table3_export_contains_levels_points_and_warnings():
    """轻量表3接口应给出入口出口水位、沿程点和警告。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_trapezoidal_case(
            start_bed_elevation=120.0,
            start_station=1000.0,
        )
    )

    export = result.get("water_profile_export")

    assert result["success"] is True
    assert export
    assert export["入口水位_m"] > export["出口水位_m"]
    assert export["points"]
    assert {"桩号_m", "渠底高程_m", "水深_m", "水位_m"}.issubset(export["points"][0])
    assert isinstance(export["warnings"], list)
    assert _has_text(export, "表3")


def test_lightweight_table3_export_marks_unavailable_profile_without_zero_levels():
    """非陡坡或无水面线时，表3轻量接口应明确不可用，不应伪装成 0 水位。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(_base_rectangular_case(i=0.0001))
    export = result.get("water_profile_export")

    assert result["success"] is True
    assert result["profile"]["available"] is False
    assert export["available"] is False
    assert export["入口水位_m"] is None
    assert export["出口水位_m"] is None
    assert export["points"] == []


def test_lightweight_table3_export_rejects_partial_failed_profile_points():
    """水面线失败但保留起点时，表3轻量接口仍应标记不可用。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        _base_rectangular_case(
            control_depth_mode="manual",
            manual_start_depth=2.1,
        )
    )
    export = result.get("water_profile_export")

    assert result["success"] is True
    assert result["profile"]["available"] is False
    assert result["profile"]["points"]
    assert export["available"] is False
    assert export["入口水位_m"] is None
    assert export["出口水位_m"] is None
    assert export["points"] == []


def test_formula_cards_can_render_to_svg_with_subscripts_and_double_prime():
    """第二版公式卡应能渲染为 SVG，关键下角标和双撇号不退回纯文本。"""
    core = _core_module()
    from app_渠系计算前端.formula_renderer import render_latex_svg

    result = core.quick_calculate_spillway_steep_chute(_base_rectangular_case())
    cards = result.get("formula_cards") or []
    latex_text = "\n".join(card["latex"] for card in cards)

    assert r"Q_{\text{cap}}" in latex_text
    assert r"h_c''" in latex_text
    assert r"L_r" in latex_text
    assert all(render_latex_svg(card["latex"], fontsize=14) for card in cards)


def test_calculation_principles_cover_audit_level_core_steps():
    """计算原理应覆盖审查所需的完整流程、公式和本次代入值。"""
    core = _core_module()
    from app_渠系计算前端.formula_renderer import render_latex_svg
    from app_渠系计算前端.spillway_steep_chute.principles import build_calculation_principles

    result = core.quick_calculate_spillway_steep_chute(_base_rectangular_case())
    principles = build_calculation_principles(result)
    names = [item["step"] for item in principles]
    formula_text = "\n".join(item["formula"] for item in principles)
    substituted_text = "\n".join(item["substitution"] for item in principles)
    user_text = "\n".join(
        str(item.get(key, ""))
        for item in principles
        for key in ("step", "purpose", "formula_text", "variables", "substitution", "result", "explanation", "source")
    )
    forbidden_text = [
        "trapezoidal",
        "rectangular",
        "manual",
        "backwater",
        "control",
        "wall",
        "cap",
        "Qcap",
        "Hwall",
        "hcontrol",
        "L_delta_b",
        "Lmin",
        r"begin{cases}",
        r"end{cases}",
    ]

    assert len(principles) >= 8
    for expected in ["基础断面与水力要素", "正常水深", "临界水深", "坡型判别", "水面线逐段计算", "掺气水深与侧墙高度", "水跃与消力池", "出口整流段"]:
        assert expected in names
    assert r"\chi=b+2h\sqrt{1+m^2}" in formula_text
    assert r"R=\frac{A}{\chi}" in formula_text
    assert "χ 为湿周" in user_text
    assert "P 为湿周" not in user_text
    assert r"Q_{\text{过流}}" in formula_text
    assert r"h_c''" in formula_text
    assert r"L_r" in formula_text
    assert all(render_latex_svg(item["formula"], fontsize=14) for item in principles)
    for forbidden in forbidden_text:
        assert forbidden not in formula_text
        assert forbidden not in user_text
    for forbidden in ["alpha", "epsilon", "zeta", "Delta"]:
        assert forbidden not in user_text
    assert "本次" not in substituted_text
    assert "Q=" in substituted_text
    assert "n=0.0140" in substituted_text
    assert "i=0.010000" in substituted_text


def test_precalculation_principles_show_formulas_inputs_and_pending_results():
    """计算前原理预览应展示公式、当前输入和待计算结果占位。"""
    from app_渠系计算前端.formula_renderer import render_latex_svg
    from app_渠系计算前端.spillway_steep_chute.principles import build_precalculation_principles

    principles = build_precalculation_principles(
        {
            "project_name": "预览工况",
            "section_type": "矩形",
            "design_flow": "12.5",
            "channel_width": "2.0",
            "side_slope": "",
            "chute_length": "30",
            "bed_slope": "0.01",
            "roughness": "0.014",
            "profile_mode_label": "已知长度求末端水深",
            "control_depth_mode_label": "取临界水深",
            "aeration_coefficient": "1.2",
            "sidewall_freeboard_m": "0.4",
            "pool_depth_factor": "1.10",
            "outlet_rectification_factor": "10.0",
        }
    )
    names = [item["step"] for item in principles]
    visible_text = "\n".join(
        str(item.get(key, ""))
        for item in principles
        for key in ("step", "purpose", "formula", "variables", "substitution", "result", "explanation", "source")
    )

    assert len(principles) >= 10
    for expected in ["基础断面与水力要素", "正常水深", "临界水深", "坡型判别", "水面线逐段计算", "水跃与消力池", "规范校核与风险提示"]:
        assert expected in names
    assert "Q=12.5" in visible_text
    assert "b=2.0" in visible_text
    assert "n=0.014" in visible_text
    assert "i=0.01" in visible_text
    assert r"\chi=b+2h\sqrt{1+m^2}" in visible_text
    assert "χ 为湿周" in visible_text
    assert "P 为湿周" not in visible_text
    assert "计算后生成" in visible_text
    assert "PRD" not in visible_text
    assert all(render_latex_svg(item["formula"], fontsize=14) for item in principles)
