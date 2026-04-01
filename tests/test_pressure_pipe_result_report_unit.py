# -*- coding: utf-8 -*-
"""有压管道结果报告文本格式单元测试。"""

from 推求水面线.utils.pressure_pipe_result_helpers import (
    build_pressure_pipe_transition_note,
    format_pressure_pipe_record_detail,
    format_pressure_pipe_calc_batch_text,
)


def test_batch_report_contains_summary_and_details():
    batch = {
        "last_run_at": "2026-03-04 10:20:30",
        "records": [
            {
                "identity": "1::牛马道",
                "flow_section": "1",
                "name": "牛马道",
                "status": "success",
                "data_mode": "空间模式（平面+纵断面）",
                "Q": 3.0,
                "D": 2.0,
                "material_key": "预应力钢筒混凝土管",
                "total_length": 120.123456,
                "pipe_velocity": 1.234567,
                "friction_loss": 0.345678,
                "total_bend_loss": 0.456789,
                "inlet_transition_loss": 0.567891,
                "outlet_transition_loss": 0.123456,
                "total_head_loss": 1.493814,
                "sensitivity_material": "球墨铸铁管",
                "sensitivity_main_f": 223200.0,
                "sensitivity_low_f": 189900.0,
                "sensitivity_low_friction_loss": 0.301234,
                "sensitivity_low_total_head_loss": 1.44937,
                "sensitivity_delta_total_head_loss": -0.044444,
                "calc_steps": "1. 管内流速\n2. 管道总长度\n7. 总水头损失",
            },
            {
                "identity": "2::牛马道",
                "flow_section": "2",
                "name": "牛马道",
                "status": "failed",
                "error": "设计流量无效",
            },
        ],
    }

    txt = format_pressure_pipe_calc_batch_text(batch, precision=4)
    assert "【有压管道计算详情】" in txt
    assert "共2条，成功1条，失败1条" in txt
    assert "流量段=1  名称=牛马道" in txt
    assert "数据模式=空间模式（平面+纵断面）" in txt
    assert "总损失: ΔH=1.4938 m" in txt
    assert "沿程=0.3457 m" in txt
    assert "球墨铸铁管 f 上下限对比: 已自动生成" in txt
    assert "总损失(下限f)=1.4494 m" in txt
    assert "ΔH(下限-主值)=-0.0444 m" in txt
    assert "失败原因: 设计流量无效" in txt


def test_build_pressure_pipe_transition_note_merges_both_sides():
    note = build_pressure_pipe_transition_note(
        has_inlet_transition=False,
        inlet_transition_reason="紧邻有压同类结构，无渐变段",
        has_outlet_transition=False,
        outlet_transition_reason="紧邻有压同类结构，无渐变段",
    )

    assert note == "进口侧紧邻有压同类结构，无渐变段；出口侧紧邻有压同类结构，无渐变段"


def test_record_detail_for_anchor_row_uses_explanation_instead_of_failure_text():
    txt = format_pressure_pipe_record_detail(
        {
            "flow_section": "1",
            "name": "流量段1 第1行有压管道",
            "status": "success",
            "writeback_enabled": False,
            "note": "整线起点，不计算本行水头损失",
            "calc_steps": "【xx管整线起点】\n本行位于整线起点，仅作为后续线路的起算位置。",
        },
        precision=4,
    )

    assert "[成功]" in txt
    assert "说明: 整线起点，不计算本行水头损失" in txt
    assert "失败原因" not in txt
    assert "输入参数:" not in txt


def test_batch_report_includes_chain_summary_and_member_rollup():
    batch = {
        "last_run_at": "2026-03-31 10:20:30",
        "chain_summaries": [
            {
                "chain_id": "chain-2-1",
                "flow_section": "2",
                "display_name": "流量段2 连续承压链1",
                "total_head_loss": 0.3854,
                "member_count": 3,
                "success_count": 3,
                "failed_count": 0,
                "member_results": [
                    {
                        "display_name": "流量段2 第1行有压管道",
                        "structure_type": "有压管道",
                        "status": "success",
                        "writeback_enabled": False,
                        "total_head_loss": 0.0,
                        "note": "链起点锚点，本行不写回",
                    },
                    {
                        "display_name": "半兽人",
                        "structure_type": "隧洞-圆形",
                        "status": "success",
                        "writeback_enabled": True,
                        "total_head_loss": 0.2312,
                    },
                    {
                        "display_name": "流量段2 第8行有压管道",
                        "structure_type": "有压管道",
                        "status": "success",
                        "writeback_enabled": True,
                        "total_head_loss": 0.1542,
                    },
                ],
            }
        ],
        "records": [
            {
                "identity": "flow2-row1",
                "flow_section": "2",
                "name": "流量段2 第1行有压管道",
                "status": "success",
                "total_head_loss": 0.0,
                "note": "链起点锚点，本行不写回",
            },
            {
                "identity": "flow2-row4",
                "flow_section": "2",
                "name": "半兽人",
                "status": "success",
                "total_head_loss": 0.2312,
            },
            {
                "identity": "flow2-row8",
                "flow_section": "2",
                "name": "流量段2 第8行有压管道",
                "status": "success",
                "total_head_loss": 0.1542,
            },
        ],
    }

    txt = format_pressure_pipe_calc_batch_text(batch, precision=4)

    assert "【连续承压链汇总】" in txt
    assert "流量段=2  链路=流量段2 连续承压链1" in txt
    assert "链总损失: ΔH=0.3854 m" in txt
    assert "成员统计: 共3个，成功3个，失败0个" in txt
    assert "成员1: 有压管道 | 流量段2 第1行有压管道 | 锚点" in txt
    assert "成员2: 隧洞-圆形 | 半兽人 | ΔH=0.2312 m" in txt
    assert "成员3: 有压管道 | 流量段2 第8行有压管道 | ΔH=0.1542 m" in txt
