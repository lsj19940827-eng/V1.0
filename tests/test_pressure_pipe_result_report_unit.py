# -*- coding: utf-8 -*-
"""有压管道结果报告文本格式单元测试。"""

from 推求水面线.utils.pressure_pipe_result_helpers import format_pressure_pipe_calc_batch_text


def test_batch_report_contains_summary_and_details():
    batch = {
        "last_run_at": "2026-03-04 10:20:30",
        "sensitivity_enabled": True,
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
    assert "球墨铸铁管 f 上下限对比: 开启" in txt
    assert "总损失(下限f)=1.4494 m" in txt
    assert "ΔH(下限-主值)=-0.0444 m" in txt
    assert "失败原因: 设计流量无效" in txt
