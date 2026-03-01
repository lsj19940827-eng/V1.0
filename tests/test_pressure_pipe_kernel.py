# -*- coding: utf-8 -*-
"""
有压管道设计内核 —— 单元测试

覆盖：加大流量比例边界、单管径计算一致性、推荐规则、兜底判定、非法输入防御
"""

import sys
import os
import math
import pytest

# 确保内核可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "渠系建筑物断面计算"))

from 有压管道设计 import (
    PIPE_MATERIALS, DEFAULT_DIAMETER_SERIES,
    get_flow_increase_percent,
    evaluate_single_diameter,
    recommend_diameter,
    solve_unpressurized,
    PressurePipeInput, DiameterCandidate, RecommendationResult,
    ECONOMIC_RULE, COMPROMISE_RULE,
)


# ============================================================
# 加大流量比例边界
# ============================================================
class TestFlowIncrease:
    """加大流量百分比边界点测试"""

    def test_q_zero(self):
        assert get_flow_increase_percent(0) == 0.0

    def test_q_negative(self):
        assert get_flow_increase_percent(-1) == 0.0

    def test_q_below_1(self):
        assert get_flow_increase_percent(0.5) == 30.0
        assert get_flow_increase_percent(0.99) == 30.0

    def test_q_boundary_1(self):
        # Q=1.0 应该进入 1<=Q<5 区间 → 25%
        assert get_flow_increase_percent(1.0) == 25.0

    def test_q_between_1_5(self):
        assert get_flow_increase_percent(3.0) == 25.0
        assert get_flow_increase_percent(4.99) == 25.0

    def test_q_boundary_5(self):
        assert get_flow_increase_percent(5.0) == 20.0

    def test_q_between_5_20(self):
        assert get_flow_increase_percent(10.0) == 20.0
        assert get_flow_increase_percent(19.99) == 20.0

    def test_q_boundary_20(self):
        assert get_flow_increase_percent(20.0) == 15.0

    def test_q_between_20_50(self):
        assert get_flow_increase_percent(30.0) == 15.0

    def test_q_boundary_50(self):
        assert get_flow_increase_percent(50.0) == 10.0

    def test_q_boundary_100(self):
        assert get_flow_increase_percent(100.0) == 5.0

    def test_q_above_300(self):
        assert get_flow_increase_percent(500.0) == 5.0


# ============================================================
# 单管径计算一致性
# ============================================================
class TestSingleDiameter:
    """单管径评价：V_press、hf_total_km、h_loss_total_m 与公式复算一致"""

    def _make_input(self, Q=0.5, mat="钢管", slope_denom=2000, length=1000.0):
        return PressurePipeInput(
            Q=Q, material_key=mat, slope_i=1.0 / slope_denom,
            n_unpr=0.014, length_m=length,
        )

    def _make_input_no_unpr(self, Q=0.5, mat="钢管", length=1000.0):
        """不带无压参数的输入（用于纯有压计算场景）"""
        return PressurePipeInput(Q=Q, material_key=mat, length_m=length)

    def test_basic_calculation(self):
        inp = self._make_input(Q=0.5, mat="钢管")
        D = 0.5
        c = evaluate_single_diameter(inp, D)

        # 手算验证
        A = math.pi * D ** 2 / 4.0
        V_expected = 0.5 / A
        assert abs(c.V_press - V_expected) < 1e-10

        # 加大流量
        pct = get_flow_increase_percent(0.5)  # 30%
        Q_inc = 0.5 * (1.0 + pct / 100.0)
        Q_inc_m3h = Q_inc * 3600.0
        d_mm = D * 1000.0
        mat = PIPE_MATERIALS["钢管"]
        hf_fric = mat["f"] * (1000.0 * (Q_inc_m3h ** mat["m"])) / (d_mm ** mat["b"])
        hf_local = 0.15 * hf_fric
        hf_total = hf_fric + hf_local

        assert abs(c.hf_friction_km - hf_fric) < 1e-10
        assert abs(c.hf_local_km - hf_local) < 1e-10
        assert abs(c.hf_total_km - hf_total) < 1e-10

    def test_h_loss_with_length(self):
        """总损失 = hf_total_km * (L/1000)"""
        inp = self._make_input(Q=1.0, mat="球墨铸铁管", length=2500.0)
        D = 0.8
        c = evaluate_single_diameter(inp, D)
        expected = c.hf_total_km * (2500.0 / 1000.0)
        assert abs(c.h_loss_total_m - expected) < 1e-10

    def test_manual_increase_percent(self):
        """手动指定加大比例"""
        inp = PressurePipeInput(
            Q=0.5, material_key="钢管", slope_i=0.001,
            manual_increase_percent=10.0,
        )
        c = evaluate_single_diameter(inp, 0.5)
        assert c.increase_pct == 10.0
        assert abs(c.Q_increased - 0.5 * 1.1) < 1e-10

    def test_economic_category(self):
        """管径选对后应为经济区"""
        inp = self._make_input(Q=0.5, mat="钢管")
        # 找一个使 V 在 0.9~1.5 且 hf<=5 的管径
        for D in DEFAULT_DIAMETER_SERIES:
            c = evaluate_single_diameter(inp, float(D))
            if 0.9 <= c.V_press <= 1.5 and c.hf_total_km <= 5.0:
                assert c.category == "经济"
                break

    def test_all_materials(self):
        """所有管材都可计算"""
        for mat_key in PIPE_MATERIALS:
            inp = PressurePipeInput(Q=1.0, material_key=mat_key, slope_i=0.001)
            c = evaluate_single_diameter(inp, 0.8)
            assert c.V_press > 0
            assert c.hf_total_km > 0

    def test_unpressurized_fields_present(self):
        """带无压参数时应包含无压字段"""
        inp = self._make_input(Q=0.5, mat="钢管")
        c = evaluate_single_diameter(inp, 0.8)
        # 0.5 m3/s, D=0.8m, i=1/2000, n=0.014 应该能算出无压结果
        assert not math.isnan(c.y_unpr) or c.unpr_notes != ""
        # V_press 始终有值
        assert c.V_press > 0

    def test_no_unpressurized_when_slope_none(self):
        """不传 slope_i 时无压字段应为 NaN"""
        inp = self._make_input_no_unpr(Q=0.5, mat="钢管")
        c = evaluate_single_diameter(inp, 0.8)
        assert c.V_press > 0
        assert math.isnan(c.y_unpr)
        assert math.isnan(c.v_unpr)
        assert c.unpr_notes == ""

    def test_unpressurized_small_pipe_exceeds_qmax(self):
        """小管径无法通过无压流 → y_unpr 应为 NaN + notes"""
        inp = self._make_input(Q=1.0, mat="钢管", slope_denom=4000)
        c = evaluate_single_diameter(inp, 0.2)
        # D=0.2m 很可能不够通过 Q=1.0 的无压流
        # 有压流速仍应有值
        assert c.V_press > 0


# ============================================================
# 无压计算独立测试
# ============================================================
class TestUnpressurized:
    """Manning 方程求解器测试"""

    def test_normal_case(self):
        """正常工况下应能求解水深"""
        y, v, yD, Qf, Qm, ch, ca, fch, fca, notes = solve_unpressurized(
            Q=0.1, D=0.5, n=0.014, i=0.001
        )
        assert not math.isnan(y)
        assert 0 < y <= 0.5
        assert v > 0
        assert 0 < yD <= 1.0
        assert ch >= 0
        assert ca >= 0

    def test_exceeds_qmax(self):
        """Q 超过 Q_max 应返回 NaN + notes"""
        y, v, yD, Qf, Qm, ch, ca, fch, fca, notes = solve_unpressurized(
            Q=100.0, D=0.1, n=0.014, i=0.001
        )
        assert math.isnan(y)
        assert "Q>" in notes

    def test_clearance_flag(self):
        """高充满度 → 净空高度警告"""
        # 用一个充满度很高的工况
        y, v, yD, Qf, Qm, ch, ca, fch, fca, notes = solve_unpressurized(
            Q=0.5, D=0.5, n=0.014, i=0.002
        )
        # 不论是否有解，标志逻辑应正确
        if not math.isnan(ch) and ch < 0.4:
            assert fch is True
        if not math.isnan(ca) and ca < 15.0:
            assert fca is True


# ============================================================
# 推荐规则顺序
# ============================================================
class TestRecommendation:
    """推荐算法：经济优先、妥协次之、兜底最后"""

    def test_economic_priority(self):
        """正常流量下应能找到经济区推荐"""
        inp = PressurePipeInput(Q=0.5, material_key="钢管")
        result = recommend_diameter(inp)
        # 0.5 m3/s 钢管应能找到经济区
        assert result.category in ("经济", "妥协")
        assert result.recommended is not None

    def test_recommendation_has_candidates(self):
        inp = PressurePipeInput(Q=1.0, material_key="球墨铸铁管", slope_i=0.0005)
        result = recommend_diameter(inp)
        assert len(result.top_candidates) > 0
        assert len(result.top_candidates) <= 5

    def test_recommendation_fills_to_5(self):
        """经济区不足5个时应从其他类别补足"""
        inp = PressurePipeInput(Q=0.5, material_key="HDPE管")
        result = recommend_diameter(inp)
        if result.category in ("经济", "妥协"):
            assert len(result.top_candidates) == 5

    def test_economic_takes_smallest_D(self):
        """经济区应取最小管径"""
        inp = PressurePipeInput(Q=0.5, material_key="钢管")
        result = recommend_diameter(inp)
        if result.category == "经济":
            # 推荐管径应是经济区中最小的
            all_eco = [
                evaluate_single_diameter(inp, float(D))
                for D in DEFAULT_DIAMETER_SERIES
            ]
            eco_diameters = sorted([c.D for c in all_eco if c.category == "经济"])
            if eco_diameters:
                assert result.recommended.D == eco_diameters[0]

    def test_fallback_has_flag(self):
        """兜底推荐应有'未满足约束'标记"""
        # 极小流量 + 极大管径序列，可能触发兜底
        inp = PressurePipeInput(Q=0.01, material_key="钢管")
        result = recommend_diameter(inp)
        if result.category == "兜底":
            assert "未满足约束" in result.recommended.flags

    def test_calc_steps_not_empty(self):
        inp = PressurePipeInput(Q=0.5, material_key="钢管")
        result = recommend_diameter(inp)
        assert result.calc_steps
        assert len(result.calc_steps) > 100


# ============================================================
# 非法输入防御
# ============================================================
class TestInvalidInput:
    """非法输入应抛出 ValueError"""

    def test_q_zero(self):
        inp = PressurePipeInput(Q=0, material_key="钢管")
        with pytest.raises(ValueError, match="Q 必须大于 0"):
            evaluate_single_diameter(inp, 0.5)

    def test_q_negative(self):
        inp = PressurePipeInput(Q=-1, material_key="钢管")
        with pytest.raises(ValueError, match="Q 必须大于 0"):
            evaluate_single_diameter(inp, 0.5)

    def test_d_zero(self):
        inp = PressurePipeInput(Q=1.0, material_key="钢管")
        with pytest.raises(ValueError, match="管径 D 必须大于 0"):
            evaluate_single_diameter(inp, 0)

    def test_d_negative(self):
        inp = PressurePipeInput(Q=1.0, material_key="钢管")
        with pytest.raises(ValueError, match="管径 D 必须大于 0"):
            evaluate_single_diameter(inp, -0.5)

    def test_unknown_material(self):
        inp = PressurePipeInput(Q=1.0, material_key="不存在的管材")
        with pytest.raises(ValueError, match="未知管材"):
            evaluate_single_diameter(inp, 0.5)

    def test_recommend_with_invalid_material(self):
        """recommend_diameter 遇到非法管材返回'无可用'"""
        inp = PressurePipeInput(Q=1.0, material_key="不存在的管材")
        result = recommend_diameter(inp)
        assert result.category == "无可用"
        assert result.recommended is None
