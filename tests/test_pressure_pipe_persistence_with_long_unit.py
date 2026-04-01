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


def test_set_result_persists_route_longitudinal_nodes_under_route_key():
    base_dir = os.path.join(os.path.dirname(__file__), "_tmp_test_data")
    os.makedirs(base_dir, exist_ok=True)
    case_dir = os.path.join(base_dir, f"ppipe_{uuid.uuid4().hex}")
    os.makedirs(case_dir, exist_ok=True)
    project_path = os.path.join(case_dir, "demo.qxproj")
    long_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 120.0, "elevation": 95.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
    ]

    try:
        manager = PressurePipeManager(project_path)
        manager.set_result(
            pipe_name="flow2-row4",
            total_head_loss=0.66,
            friction_loss=0.55,
            total_bend_loss=0.05,
            inlet_transition_loss=0.03,
            outlet_transition_loss=0.03,
            pipe_velocity=1.22,
            plan_total_length=88.0,
            data_mode="空间模式（平面+纵断面）",
            longitudinal_nodes=long_nodes,
            route_key="flow2-route1",
            route_display_name="流量段2 整线1",
        )

        raw = manager.to_dict()
        assert raw["pipes"]["flow2-row4"]["route_key"] == "flow2-route1"
        assert raw["routes"]["flow2-route1"]["display_name"] == "流量段2 整线1"
        assert raw["routes"]["flow2-route1"]["longitudinal_nodes"] == long_nodes

        loaded = manager.get_pipe_config("flow2-row4")
        assert loaded is not None
        assert loaded.route_key == "flow2-route1"
        assert loaded.route_display_name == "流量段2 整线1"
        assert loaded.longitudinal_nodes == long_nodes
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_get_pipe_config_reads_route_bucket_when_pipe_row_has_no_own_longitudinal_nodes():
    manager = PressurePipeManager()
    long_nodes = [
        {"chainage": 10.0, "elevation": 88.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 60.0, "elevation": 82.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
    ]
    manager.from_dict(
        {
            "version": "1.0",
            "last_modified": "",
            "pipes": {
                "flow3-row7": {
                    "name": "流量段3 第7行有压管道",
                    "route_key": "flow3-route2",
                    "route_display_name": "流量段3 整线2",
                    "longitudinal_nodes": [],
                }
            },
            "routes": {
                "flow3-route2": {
                    "display_name": "流量段3 整线2",
                    "longitudinal_nodes": long_nodes,
                }
            },
        }
    )

    loaded = manager.get_pipe_config("flow3-row7")
    assert loaded is not None
    assert loaded.route_key == "flow3-route2"
    assert loaded.route_display_name == "流量段3 整线2"
    assert loaded.longitudinal_nodes == long_nodes


def test_set_result_without_route_args_keeps_existing_route_binding():
    manager = PressurePipeManager()
    long_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 80.0, "elevation": 92.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
    ]
    manager.from_dict(
        {
            "version": "1.0",
            "last_modified": "",
            "pipes": {
                "flow2-row6": {
                    "name": "流量段2 第6行有压管道",
                    "route_key": "flow2-route1",
                    "route_display_name": "流量段2 整线1",
                    "longitudinal_nodes": [],
                }
            },
            "routes": {
                "flow2-route1": {
                    "display_name": "流量段2 整线1",
                    "longitudinal_nodes": long_nodes,
                }
            },
        }
    )

    manager.set_result(
        pipe_name="flow2-row6",
        total_head_loss=0.42,
        friction_loss=0.31,
        total_bend_loss=0.05,
        inlet_transition_loss=0.03,
        outlet_transition_loss=0.03,
        pipe_velocity=1.1,
        plan_total_length=75.0,
        data_mode="段级平面模式",
        longitudinal_nodes=long_nodes,
    )

    raw = manager.to_dict()
    assert raw["pipes"]["flow2-row6"]["route_key"] == "flow2-route1"
    assert raw["pipes"]["flow2-row6"]["route_display_name"] == "流量段2 整线1"
    assert raw["routes"]["flow2-route1"]["longitudinal_nodes"] == long_nodes
