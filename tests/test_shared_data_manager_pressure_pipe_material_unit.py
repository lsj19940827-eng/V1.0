# -*- coding: utf-8 -*-
"""
共享数据管理器 - 有压管道字段透传单元测试
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.pressure_pipe_calc import PIPE_MATERIALS, calc_friction_loss
from shared.shared_data_manager import SharedDataManager
from utils.pressure_pipe_common import resolve_pressure_pipe_material


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


def test_siphon_pipe_material_is_preserved_in_shared_data_manager():
    """倒虹吸的管材应被保留并继续写回节点参数。"""
    manager = SharedDataManager()
    manager.clear_batch_results()

    payload = [{
        "success": True,
        "section_type": "倒虹吸",
        "is_siphon": True,
        "flow_section": "1",
        "building_name": "老屋基",
        "coord_X": 451333.9116,
        "coord_Y": 3047880.2791,
        "Q": 1.55,
        "n": 0.014,
        "D": 1.4,
        "turn_radius": 0.0,
        "pipe_material": "HDPE管",
    }]

    count = manager.register_batch_results(payload)
    assert count == 1

    section = manager.get_batch_results()[0]
    assert section.pipe_material == "HDPE管"
    assert section.D == 1.4

    node_params = section.to_node_params()
    section_params = node_params["section_params"]
    assert section_params["pipe_material"] == "HDPE管"
    assert section_params["D"] == 1.4


def test_pressure_pipe_like_results_preserve_original_xxpipe_section_type():
    """定向钻/顶管应保留原工艺名，同时继续走有压管道语义。"""
    manager = SharedDataManager()

    for section_type in ("定向钻", "顶管"):
        manager.clear_batch_results()
        payload = [{
            "success": True,
            "section_type": section_type,
            "is_pressure_pipe": True,
            "flow_section": "2",
            "building_name": f"{section_type}穿越段",
            "coord_X": 451333.9116,
            "coord_Y": 3047880.2791,
            "Q": 1.55,
            "n": 0.0,
            "D": 1.4,
            "turn_radius": 0.0,
            "pipe_material": "钢管",
            "local_loss_ratio": 0.0,
            "in_out_raw": "进",
        }]

        count = manager.register_batch_results(payload)

        assert count == 1
        section = manager.get_batch_results()[0]
        assert section.section_type == section_type
        assert section.pipe_material == "钢管"


def test_pressure_pipe_material_resolves_pccp_roughness_aliases():
    """PCCP管可通过后缀 n 值选择对应的有压管道 f/m/b 参数。"""
    cases = {
        "PCCP管": "预应力钢筒混凝土管",
        "PCCP管0.013": "预应力钢筒混凝土管",
        "PCCP管 0.014": "预应力钢筒混凝土管_n014",
        "PCCP管(n=0.015)": "预应力钢筒混凝土管_n015",
    }

    for raw_value, expected_key in cases.items():
        info = resolve_pressure_pipe_material(
            raw_value,
            PIPE_MATERIALS,
            default_material="预应力钢筒混凝土管",
        )

        assert info["canonical_key"] == expected_key
        assert info["recognized"] is True
        assert info["used_default"] is False


def test_pressure_pipe_material_marks_unsupported_pccp_roughness_without_blocking():
    """不支持的 PCCP n 值应回退到 n=0.013，并带上可供导入提示使用的标记。"""
    info = resolve_pressure_pipe_material(
        "PCCP管0.012",
        PIPE_MATERIALS,
        default_material="预应力钢筒混凝土管",
    )

    assert info["canonical_key"] == "预应力钢筒混凝土管"
    assert info["recognized"] is False
    assert info["used_default"] is True
    assert info["unsupported_pccp_roughness"] is True
    assert info["unsupported_pccp_roughness_value"] == "0.012"


def test_pressure_pipe_calc_supports_pccp_n015_material_key():
    """表3有压管道水损计算应能直接使用 PCCP n=0.015 参数。"""
    loss, details = calc_friction_loss(1.0, 1.0, 1000.0, "预应力钢筒混凝土管_n015")

    assert loss > 0
    assert details["f"] == 1.749e6

