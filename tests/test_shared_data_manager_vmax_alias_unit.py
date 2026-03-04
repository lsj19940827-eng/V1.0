# -*- coding: utf-8 -*-
"""SharedDataManager 对加大流速别名键的兼容性测试。"""

import pytest

from 推求水面线.shared.shared_data_manager import get_shared_data_manager


@pytest.mark.parametrize("v_key", ["V_increased", "V_max", "V_i"])
def test_register_batch_results_supports_vmax_alias_keys(v_key):
    mgr = get_shared_data_manager()
    mgr.clear_batch_results()

    payload = {
        "success": True,
        "section_type": "明渠-梯形",
        "Q": 2.0,
        "n": 0.014,
        "b_design": 1.5,
        "h_design": 1.2,
        v_key: 1.23,
    }

    count = mgr.register_batch_results([payload])
    assert count == 1

    rows = mgr.get_batch_results()
    assert len(rows) == 1
    assert rows[0].V_max == pytest.approx(1.23)

    mgr.clear_batch_results()

