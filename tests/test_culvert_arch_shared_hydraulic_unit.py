# -*- coding: utf-8 -*-
"""圆拱直墙型暗涵共享结果链路测试。"""

import pytest

from 推求水面线.shared.shared_data_manager import get_shared_data_manager, normalize_section_type_name


def test_normalize_section_type_name_maps_culvert_aliases_to_new_labels():
    """暗涵旧值应统一归一到新的结构类型口径。"""
    assert normalize_section_type_name("矩形暗涵") == "暗涵-矩形"
    assert normalize_section_type_name("暗渠") == "暗涵-矩形"
    assert normalize_section_type_name("矩形暗渠") == "暗涵-矩形"
    assert normalize_section_type_name("圆拱直墙型暗涵") == "暗涵-圆拱直墙型"


def test_shared_data_manager_preserves_culvert_arch_hidden_params():
    """共享结果应稳定保留圆拱直墙型暗涵的隐藏参数。"""
    manager = get_shared_data_manager()
    manager.clear_batch_results()

    payload = {
        "success": True,
        "section_type": "圆拱直墙型暗涵",
        "Q": 6.0,
        "n": 0.014,
        "h_design": 1.52,
        "A_design": 4.21,
        "P_design": 5.88,
        "R_hyd_design": 0.716,
        "B": 2.6,
        "H_total": 2.18,
        "H_straight": 0.92,
        "theta_deg": 140.0,
        "manual_H_straight": 0.92,
        "used_manual_H_straight": True,
        "V_max": 1.42,
    }

    count = manager.register_batch_results([payload])
    assert count == 1

    rows = manager.get_batch_results()
    assert len(rows) == 1
    result = rows[0]
    assert result.section_type == "暗涵-圆拱直墙型"
    assert result.B == pytest.approx(2.6)
    assert result.H_total == pytest.approx(2.18)
    assert result.H_straight == pytest.approx(0.92)

    node_params = result.to_node_params()
    section_params = node_params["section_params"]
    assert section_params["B"] == pytest.approx(2.6)
    assert section_params["H_total"] == pytest.approx(2.18)
    assert section_params["H_straight"] == pytest.approx(0.92)
    assert section_params["theta_deg"] == pytest.approx(140.0)
    assert section_params["manual_H_straight"] == pytest.approx(0.92)
    assert section_params["used_manual_H_straight"] is True

    manager.clear_batch_results()
