# -*- coding: utf-8 -*-
"""有压管道结果持久化结构单元测试。"""

import json

from 推求水面线.utils.pressure_pipe_result_helpers import (
    empty_pressure_pipe_calc_records,
    normalize_pressure_pipe_calc_records,
)


def test_records_roundtrip_is_stable():
    raw = {
        "last_run_at": "2026-03-04 11:22:33",
        "sensitivity_enabled": True,
        "summary": {"total": 99, "success": 88, "failed": 11},  # 将被规范化重算
        "records": [
            {
                "identity": "1::牛马道",
                "flow_section": "1",
                "name": "牛马道",
                "status": "success",
                "Q": "3.0",
                "D": 2,
                "total_head_loss": "1.234567",
                "sensitivity_main_f": "223200",
                "sensitivity_low_f": 189900,
                "sensitivity_low_total_head_loss": "1.1111",
                "calc_steps": "1. ...\n7. ...",
            },
            {
                "identity": "2::牛马道",
                "flow_section": "2",
                "name": "牛马道",
                "status": "failed",
                "error": "缺少管径",
            },
        ],
    }

    n1 = normalize_pressure_pipe_calc_records(raw)
    dumped = json.dumps(n1, ensure_ascii=False)
    loaded = json.loads(dumped)
    n2 = normalize_pressure_pipe_calc_records(loaded)

    assert n1 == n2
    assert n2["sensitivity_enabled"] is True
    assert n2["summary"] == {"total": 2, "success": 1, "failed": 1}
    assert n2["records"][0]["total_head_loss"] == 1.234567
    assert n2["records"][0]["sensitivity_main_f"] == 223200.0
    assert n2["records"][0]["sensitivity_low_total_head_loss"] == 1.1111


def test_missing_records_field_compatible_with_old_project():
    assert normalize_pressure_pipe_calc_records(None) == empty_pressure_pipe_calc_records()
    assert normalize_pressure_pipe_calc_records({}) == empty_pressure_pipe_calc_records()
