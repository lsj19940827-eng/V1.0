# -*- coding: utf-8 -*-
"""有压管道纵断面与数据模式持久化单元测试。"""

import os
import shutil
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from managers.pressure_pipe_manager import PressurePipeManager  # noqa: E402


def test_set_result_persists_data_mode_and_longitudinal_nodes():
    base_dir = os.path.join(os.path.dirname(__file__), "_tmp_test_data")
    os.makedirs(base_dir, exist_ok=True)
    case_dir = os.path.join(base_dir, f"ppipe_{uuid.uuid4().hex}")
    os.makedirs(case_dir, exist_ok=True)
    project_path = os.path.join(case_dir, "demo.qxproj")
    long_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 50.0, "elevation": 98.5, "vertical_curve_radius": 300.0, "turn_type": "ARC", "turn_angle": 12.0},
    ]

    try:
        manager = PressurePipeManager(project_path)
        manager.set_result(
            pipe_name="测试管道A",
            total_head_loss=1.23,
            friction_loss=0.80,
            total_bend_loss=0.10,
            inlet_transition_loss=0.20,
            outlet_transition_loss=0.13,
            pipe_velocity=1.45,
            plan_total_length=100.0,
            data_mode="空间模式（平面+纵断面）",
            longitudinal_nodes=long_nodes,
        )

        loaded = manager.get_pipe_config("测试管道A")
        assert loaded is not None
        assert loaded.data_mode == "空间模式（平面+纵断面）"
        assert loaded.longitudinal_nodes == long_nodes

        reloaded_manager = PressurePipeManager(project_path)
        reloaded = reloaded_manager.get_pipe_config("测试管道A")
        assert reloaded is not None
        assert reloaded.data_mode == "空间模式（平面+纵断面）"
        assert reloaded.longitudinal_nodes == long_nodes
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
