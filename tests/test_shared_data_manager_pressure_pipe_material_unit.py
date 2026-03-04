# -*- coding: utf-8 -*-
"""
共享数据管理器 - 有压管道字段透传单元测试
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from shared.shared_data_manager import SharedDataManager


def test_pressure_pipe_fields_are_preserved_in_shared_data_manager():
    """有压管道的管材/局部损失比例/进出口标识应被保留并可导出为节点参数"""
    manager = SharedDataManager()
    manager.clear_batch_results()

    payload = [{
        "success": True,
        "section_type": "有压管道",
        "is_pressure_pipe": True,
        "flow_section": "3",
        "building_name": "牛马道",
        "coord_X": 3376200.0,
        "coord_Y": 337620.0,
        "Q": 3.0,
        "n": 0.014,
        "D": 1.6,
        "turn_radius": 8.0,
        "pipe_material": "球墨铸铁管",
        "local_loss_ratio": 0.12,
        "in_out_raw": "进",
    }]

    count = manager.register_batch_results(payload)
    assert count == 1

    results = manager.get_batch_results()
    assert len(results) == 1

    section = results[0]
    assert section.pipe_material == "球墨铸铁管"
    assert section.local_loss_ratio == 0.12
    assert section.in_out_raw == "进"

    node_params = section.to_node_params()
    section_params = node_params["section_params"]
    assert section_params["pipe_material"] == "球墨铸铁管"
    assert abs(section_params["local_loss_ratio"] - 0.12) < 1e-12
    assert section_params["in_out_raw"] == "进"

