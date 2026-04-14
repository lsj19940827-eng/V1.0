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


def test_set_result_with_none_route_longitudinal_nodes_preserves_existing_route_cache():
    manager = PressurePipeManager()
    long_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 120.0, "elevation": 95.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
    ]
    manager.from_dict(
        {
            "version": "1.0",
            "last_modified": "",
            "pipes": {
                "flow2-row4": {
                    "name": "流量段2 第4行有压管道",
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
        pipe_name="flow2-row4",
        total_head_loss=0.66,
        friction_loss=0.55,
        total_bend_loss=0.05,
        inlet_transition_loss=0.03,
        outlet_transition_loss=0.03,
        pipe_velocity=1.22,
        plan_total_length=88.0,
        data_mode="空间模式（平面+纵断面）",
        longitudinal_nodes=None,
        route_key="flow2-route1",
        route_display_name="流量段2 整线1",
    )

    raw = manager.to_dict()
    assert raw["routes"]["flow2-route1"]["longitudinal_nodes"] == long_nodes

    loaded = manager.get_pipe_config("flow2-row4")
    assert loaded is not None
    assert loaded.longitudinal_nodes == long_nodes


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


def test_get_pipe_config_reads_route_profile_segments_from_dict():
    manager = PressurePipeManager()
    profile_segments = [
        {
            "segment_identity": "flow2-mixed-tunnel",
            "structure_type": "隧洞-圆形",
            "source_kind": "generated_tunnel",
            "start_mc": 0.0,
            "end_mc": 20.0,
            "longitudinal_nodes": [
                {"chainage": 0.0, "elevation": 420.0, "turn_type": "NONE"},
                {"chainage": 20.0, "elevation": 419.8, "turn_type": "NONE"},
            ],
            "warnings": [],
        }
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
                    "longitudinal_nodes": [],
                    "profile_segments": profile_segments,
                }
            },
        }
    )

    loaded = manager.get_pipe_config("flow2-row6")
    assert loaded is not None
    assert loaded.profile_segments == profile_segments


def test_set_result_persists_route_profile_segments_for_mixed_xxpipe():
    manager = PressurePipeManager()
    profile_segments = [
        {
            "segment_identity": "flow2-mixed-tunnel",
            "structure_type": "隧洞-圆形",
            "source_kind": "generated_tunnel",
            "start_mc": 0.0,
            "end_mc": 20.0,
            "longitudinal_nodes": [
                {"chainage": 0.0, "elevation": 420.0, "turn_type": "NONE"},
                {"chainage": 20.0, "elevation": 419.8, "turn_type": "NONE"},
            ],
            "warnings": [],
        },
        {
            "segment_identity": "flow2-row6",
            "structure_type": "有压管道",
            "source_kind": "non_tunnel_dxf",
            "start_mc": 20.0,
            "end_mc": 80.0,
            "longitudinal_nodes": [
                {"chainage": 20.0, "elevation": 418.0, "turn_type": "NONE"},
                {"chainage": 80.0, "elevation": 412.0, "turn_type": "NONE"},
            ],
            "warnings": [],
        },
    ]

    manager.set_result(
        pipe_name="flow2-row6",
        total_head_loss=0.42,
        friction_loss=0.31,
        total_bend_loss=0.05,
        inlet_transition_loss=0.03,
        outlet_transition_loss=0.03,
        pipe_velocity=1.1,
        plan_total_length=75.0,
        data_mode="空间模式（混合整线）",
        longitudinal_nodes=[],
        route_key="flow2-route1",
        route_display_name="流量段2 整线1",
        profile_segments=profile_segments,
    )

    raw = manager.to_dict()
    assert raw["routes"]["flow2-route1"]["profile_segments"] == profile_segments

    loaded = manager.get_pipe_config("flow2-row6")
    assert loaded is not None
    assert loaded.profile_segments == profile_segments


def test_set_result_with_empty_route_profile_segments_clears_stale_mixed_route_cache():
    manager = PressurePipeManager()
    stale_segments = [
        {
            "segment_identity": "flow2-mixed-tunnel",
            "structure_type": "隧洞-圆形",
            "source_kind": "generated_tunnel",
            "start_mc": 0.0,
            "end_mc": 20.0,
            "longitudinal_nodes": [
                {"chainage": 0.0, "elevation": 420.0, "turn_type": "NONE"},
                {"chainage": 20.0, "elevation": 419.8, "turn_type": "NONE"},
            ],
            "warnings": [],
        }
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
                    "longitudinal_nodes": [],
                    "profile_segments": stale_segments,
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
        data_mode="空间模式（整线 DXF）",
        longitudinal_nodes=[],
        route_key="flow2-route1",
        route_display_name="流量段2 整线1",
        profile_segments=[],
    )

    raw = manager.to_dict()
    assert raw["routes"]["flow2-route1"]["profile_segments"] == []

    loaded = manager.get_pipe_config("flow2-row6")
    assert loaded is not None
    assert loaded.profile_segments == []


def test_save_pressure_routes_persists_segments_bucket_and_route_profile_state():
    manager = PressurePipeManager()
    route_nodes = [
        {"chainage": 3968.95, "elevation": 405.0, "turn_type": "NONE"},
        {"chainage": 4693.42, "elevation": 398.5, "turn_type": "NONE"},
    ]
    routes = [
        {
            "route_key": "flow1-route1",
            "route_display_name": "赛金连续整线",
            "channel_level": "支渠",
            "start_row_index": 72,
            "end_row_index": 76,
            "start_mc": 3968.95,
            "end_mc": 4693.42,
            "entered_pressurized_at_row": 72,
            "profile_state": "coverage_missing",
            "segment_identities": ["flow1-row73", "flow1-row74", "flow1-row76"],
        }
    ]
    segment_results = [
        {
            "identity": "flow1-row73",
            "route_key": "flow1-route1",
            "base_name": "苟家湾",
            "member_display_name": "苟家湾（前缀段）",
            "dxf_display_name": "苟家湾",
            "structure_type": "有压管道",
            "member_role": "prefix_segment",
            "start_row_index": 72,
            "end_row_index": 72,
            "target_row_index": 72,
            "upstream_row_index": 71,
            "start_mc": 3968.95,
            "end_mc": 3971.87,
            "is_pressurized_tail_member": True,
            "status": "success",
            "friction_loss": 0.08,
            "bend_loss": 0.0,
            "local_loss": 0.0,
            "total_loss": 0.08,
            "applied_to_row_index": 73,
            "note": "前缀段结果已写入下游入口行",
            "computed_from_profile_source": "route_profile",
            "longitudinal_nodes": [
                {"chainage": 3968.95, "elevation": 405.0, "turn_type": "NONE"},
                {"chainage": 3971.87, "elevation": 404.9, "turn_type": "NONE"},
            ],
            "profile_state": "ok",
        },
        {
            "identity": "flow1-row74",
            "route_key": "flow1-route1",
            "base_name": "大石包",
            "member_display_name": "大石包",
            "dxf_display_name": "大石包",
            "structure_type": "定向钻",
            "member_role": "special_segment",
            "start_row_index": 73,
            "end_row_index": 74,
            "target_row_index": 73,
            "upstream_row_index": 72,
            "start_mc": 3971.87,
            "end_mc": 4366.58,
            "is_pressurized_tail_member": True,
            "status": "success",
            "friction_loss": 0.0,
            "bend_loss": 0.02,
            "local_loss": 0.01,
            "total_loss": 0.03,
            "applied_to_row_index": 73,
            "note": "",
            "computed_from_profile_source": "route_profile",
            "longitudinal_nodes": route_nodes,
            "profile_state": "ok",
        },
    ]

    manager.save_pressure_routes(
        routes,
        route_profiles={"flow1-route1": route_nodes},
        segment_results=segment_results,
    )

    raw = manager.to_dict()
    assert raw["routes"]["flow1-route1"]["profile_state"] == "coverage_missing"
    assert raw["routes"]["flow1-route1"]["entered_pressurized_at_row"] == 72
    assert raw["routes"]["flow1-route1"]["segment_identities"] == ["flow1-row73", "flow1-row74", "flow1-row76"]
    assert raw["segments"]["flow1-row73"]["member_display_name"] == "苟家湾（前缀段）"
    assert raw["segments"]["flow1-row73"]["dxf_display_name"] == "苟家湾"
    assert raw["segments"]["flow1-row74"]["member_display_name"] == "大石包"
    assert raw["segments"]["flow1-row74"]["dxf_display_name"] == "大石包"


def test_save_pressure_routes_replaces_stale_route_snapshots_in_active_range():
    manager = PressurePipeManager()
    manager.from_dict(
        {
            "version": "1.0",
            "last_modified": "",
            "pipes": {
                "1::苟家湾::rows83": {
                    "name": "苟家湾（前缀段）",
                    "route_key": "pressure-route-1-r83-115",
                    "route_display_name": "旧整线",
                    "start_row_index": 72,
                    "end_row_index": 72,
                },
                "1::大石包::rows84-85": {
                    "name": "大石包",
                    "route_key": "pressure-route-1-r83-115",
                    "route_display_name": "旧整线",
                    "start_row_index": 73,
                    "end_row_index": 74,
                },
            },
            "routes": {
                "pressure-route-1-r83-115": {
                    "display_name": "旧整线",
                    "start_row_index": 72,
                    "end_row_index": 75,
                    "segment_identities": ["1::苟家湾::rows83", "1::大石包::rows84-85"],
                    "longitudinal_nodes": [],
                }
            },
            "segments": {
                "1::苟家湾::rows83": {
                    "identity": "1::苟家湾::rows83",
                    "route_key": "pressure-route-1-r83-115",
                    "member_display_name": "苟家湾（前缀段）",
                    "start_row_index": 72,
                    "end_row_index": 72,
                },
                "1::大石包::rows84-85": {
                    "identity": "1::大石包::rows84-85",
                    "route_key": "pressure-route-1-r83-115",
                    "member_display_name": "大石包",
                    "start_row_index": 73,
                    "end_row_index": 74,
                },
            },
        }
    )

    route_nodes = [
        {"chainage": 3968.95, "elevation": 405.0, "turn_type": "NONE"},
        {"chainage": 4693.42, "elevation": 398.5, "turn_type": "NONE"},
    ]
    manager.save_pressure_routes(
        [
            {
                "route_key": "flow1-route1",
                "route_display_name": "赛金连续整线",
                "channel_level": "支渠",
                "start_row_index": 72,
                "end_row_index": 75,
                "start_mc": 3968.95,
                "end_mc": 4693.42,
                "entered_pressurized_at_row": 72,
                "profile_state": "ok",
                "segment_identities": ["flow1-row73", "flow1-row74"],
            }
        ],
        route_profiles={"flow1-route1": route_nodes},
        segment_results=[
            {
                "identity": "flow1-row73",
                "route_key": "flow1-route1",
                "member_display_name": "苟家湾（前缀段）",
                "dxf_display_name": "苟家湾",
                "start_row_index": 72,
                "end_row_index": 72,
                "target_row_index": 72,
                "upstream_row_index": 71,
                "start_mc": 3968.95,
                "end_mc": 3971.87,
                "status": "success",
                "total_loss": 0.08,
            },
            {
                "identity": "flow1-row74",
                "route_key": "flow1-route1",
                "member_display_name": "大石包",
                "dxf_display_name": "大石包",
                "start_row_index": 73,
                "end_row_index": 74,
                "target_row_index": 73,
                "upstream_row_index": 72,
                "start_mc": 3971.87,
                "end_mc": 4366.58,
                "status": "success",
                "total_loss": 0.03,
            },
        ],
    )

    raw = manager.to_dict()
    assert "pressure-route-1-r83-115" not in raw["routes"]
    assert "1::苟家湾::rows83" not in raw["segments"]
    assert "1::大石包::rows84-85" not in raw["segments"]
    assert "1::苟家湾::rows83" not in raw["pipes"]
    assert "1::大石包::rows84-85" not in raw["pipes"]
    assert raw["segments"]["flow1-row73"]["route_key"] == "flow1-route1"
    assert raw["segments"]["flow1-row74"]["route_key"] == "flow1-route1"


def test_save_pressure_routes_preserves_existing_profile_segments_and_tunnel_fallback_fields():
    manager = PressurePipeManager()
    profile_segments = [
        {
            "segment_identity": "flow9-row3",
            "structure_type": "隧洞-圆形",
            "source_kind": "generated_tunnel",
            "start_mc": 0.0,
            "end_mc": 60.0,
            "longitudinal_nodes": [
                {"chainage": 0.0, "elevation": 420.0, "turn_type": "NONE"},
                {"chainage": 60.0, "elevation": 418.8, "turn_type": "NONE"},
            ],
            "warnings": [],
        }
    ]
    manager.from_dict(
        {
            "version": "1.0",
            "last_modified": "",
            "pipes": {
                "flow9-row3": {
                    "name": "9#隧洞",
                    "route_key": "flow9-route1",
                    "route_display_name": "9号整线",
                    "segment_geometry_source": "generated_tunnel",
                    "tunnel_invert_inlet": 416.5,
                    "tunnel_slope_i": 0.0015,
                    "tunnel_invert_outlet_check": 416.41,
                    "tunnel_roughness_n": 0.014,
                    "tunnel_profile_mode": "水力核算模式",
                    "tunnel_section_type": "圆形",
                    "tunnel_section_params": {"D": 2.4},
                }
            },
            "routes": {
                "flow9-route1": {
                    "display_name": "9号整线",
                    "start_row_index": 10,
                    "end_row_index": 10,
                    "longitudinal_nodes": [],
                    "profile_segments": profile_segments,
                }
            },
            "segments": {
                "flow9-row3": {
                    "identity": "flow9-row3",
                    "route_key": "flow9-route1",
                    "route_display_name": "9号整线",
                    "segment_geometry_source": "generated_tunnel",
                    "tunnel_invert_inlet": 416.5,
                    "tunnel_slope_i": 0.0015,
                    "tunnel_invert_outlet_check": 416.41,
                    "tunnel_roughness_n": 0.014,
                    "tunnel_profile_mode": "水力核算模式",
                    "tunnel_section_type": "圆形",
                    "tunnel_section_params": {"D": 2.4},
                }
            },
        }
    )

    manager.save_pressure_routes(
        [
            {
                "route_key": "flow9-route1",
                "route_display_name": "9号整线",
                "channel_level": "干渠",
                "start_row_index": 10,
                "end_row_index": 10,
                "start_mc": 0.0,
                "end_mc": 60.0,
                "entered_pressurized_at_row": 10,
                "profile_state": "ok",
                "segment_identities": ["flow9-row3"],
            }
        ],
        route_profiles={"flow9-route1": []},
        segment_results=[
            {
                "identity": "flow9-row3",
                "route_key": "flow9-route1",
                "route_display_name": "9号整线",
                "base_name": "9#隧洞",
                "member_display_name": "9#隧洞",
                "dxf_display_name": "9#隧洞",
                "structure_type": "隧洞",
                "member_role": "tunnel_segment",
                "start_row_index": 10,
                "end_row_index": 10,
                "target_row_index": 10,
                "upstream_row_index": 9,
                "applied_to_row_index": 10,
                "start_mc": 0.0,
                "end_mc": 60.0,
                "status": "success",
                "friction_loss": 0.12,
                "bend_loss": 0.0,
                "local_loss": 0.01,
                "total_loss": 0.13,
                "computed_from_profile_source": "route_profile",
                "longitudinal_nodes": [],
                "profile_state": "ok",
            }
        ],
    )

    raw = manager.to_dict()
    assert raw["routes"]["flow9-route1"]["profile_segments"] == profile_segments
    assert raw["segments"]["flow9-row3"]["tunnel_slope_i"] == 0.0015
    assert raw["segments"]["flow9-row3"]["tunnel_section_type"] == "圆形"
    assert raw["pipes"]["flow9-row3"]["tunnel_roughness_n"] == 0.014
    assert raw["pipes"]["flow9-row3"]["tunnel_section_params"] == {"D": 2.4}

    loaded = manager.get_pipe_config("flow9-row3")
    assert loaded is not None
    assert loaded.profile_segments == profile_segments
    assert loaded.tunnel_slope_i == 0.0015
    assert loaded.tunnel_section_type == "圆形"
    assert loaded.tunnel_section_params == {"D": 2.4}


def test_save_pressure_routes_without_route_profile_preserves_existing_route_longitudinal_nodes():
    manager = PressurePipeManager()
    route_longitudinal_nodes = [
        {"chainage": 0.0, "elevation": 420.0, "turn_type": "NONE"},
        {"chainage": 60.0, "elevation": 418.8, "turn_type": "NONE"},
    ]
    manager.from_dict(
        {
            "version": "1.0",
            "last_modified": "",
            "pipes": {
                "flow9-row3": {
                    "name": "9#隧洞",
                    "route_key": "flow9-route1",
                    "route_display_name": "9号整线",
                    "longitudinal_nodes": [],
                }
            },
            "routes": {
                "flow9-route1": {
                    "display_name": "9号整线",
                    "start_row_index": 10,
                    "end_row_index": 10,
                    "longitudinal_nodes": route_longitudinal_nodes,
                    "profile_segments": [],
                }
            },
            "segments": {
                "flow9-row3": {
                    "identity": "flow9-row3",
                    "route_key": "flow9-route1",
                    "route_display_name": "9号整线",
                }
            },
        }
    )

    manager.save_pressure_routes(
        [
            {
                "route_key": "flow9-route1",
                "route_display_name": "9号整线",
                "channel_level": "干渠",
                "start_row_index": 10,
                "end_row_index": 10,
                "start_mc": 0.0,
                "end_mc": 60.0,
                "entered_pressurized_at_row": 10,
                "profile_state": "ok",
                "segment_identities": ["flow9-row3"],
            }
        ],
        route_profiles={},
        segment_results=[
            {
                "identity": "flow9-row3",
                "route_key": "flow9-route1",
                "route_display_name": "9号整线",
                "base_name": "9#隧洞",
                "member_display_name": "9#隧洞",
                "dxf_display_name": "9#隧洞",
                "structure_type": "隧洞",
                "member_role": "tunnel_segment",
                "start_row_index": 10,
                "end_row_index": 10,
                "target_row_index": 10,
                "upstream_row_index": 9,
                "applied_to_row_index": 10,
                "start_mc": 0.0,
                "end_mc": 60.0,
                "status": "success",
                "friction_loss": 0.12,
                "bend_loss": 0.0,
                "local_loss": 0.01,
                "total_loss": 0.13,
                "computed_from_profile_source": "route_profile",
                "longitudinal_nodes": [],
                "profile_state": "ok",
            }
        ],
    )

    raw = manager.to_dict()
    assert raw["routes"]["flow9-route1"]["longitudinal_nodes"] == route_longitudinal_nodes

    loaded = manager.get_pipe_config("flow9-row3")
    assert loaded is not None
    assert loaded.longitudinal_nodes == route_longitudinal_nodes


def test_get_pipe_config_prefers_pipe_bucket_and_falls_back_to_route_and_segment():
    manager = PressurePipeManager()
    pipe_longitudinal_nodes = [
        {"chainage": 5.0, "elevation": 430.0, "turn_type": "NONE"},
        {"chainage": 35.0, "elevation": 428.0, "turn_type": "NONE"},
    ]
    route_profile_segments = [
        {
            "segment_identity": "flow8-row2",
            "structure_type": "隧洞-圆形",
            "source_kind": "generated_tunnel",
            "start_mc": 5.0,
            "end_mc": 35.0,
            "longitudinal_nodes": [
                {"chainage": 5.0, "elevation": 429.0, "turn_type": "NONE"},
                {"chainage": 35.0, "elevation": 427.6, "turn_type": "NONE"},
            ],
            "warnings": [],
        }
    ]
    manager.from_dict(
        {
            "version": "1.0",
            "last_modified": "",
            "pipes": {
                "flow8-row2": {
                    "name": "8#隧洞",
                    "route_key": "flow8-route1",
                    "route_display_name": "",
                    "longitudinal_nodes": pipe_longitudinal_nodes,
                    "profile_segments": [],
                    "tunnel_slope_i": 0.0022,
                    "tunnel_section_type": "",
                    "tunnel_profile_mode": "",
                    "tunnel_section_params": {},
                }
            },
            "routes": {
                "flow8-route1": {
                    "display_name": "8号整线",
                    "longitudinal_nodes": [],
                    "profile_segments": route_profile_segments,
                }
            },
            "segments": {
                "flow8-row2": {
                    "identity": "flow8-row2",
                    "route_key": "flow8-route1",
                    "route_display_name": "8号整线",
                    "longitudinal_nodes": [],
                    "segment_geometry_source": "generated_tunnel",
                    "tunnel_slope_i": 0.0018,
                    "tunnel_roughness_n": 0.013,
                    "tunnel_profile_mode": "水力核算模式",
                    "tunnel_section_type": "圆形",
                    "tunnel_section_params": {"D": 2.1},
                }
            },
        }
    )

    loaded = manager.get_pipe_config("flow8-row2")
    assert loaded is not None
    assert loaded.route_display_name == "8号整线"
    assert loaded.longitudinal_nodes == pipe_longitudinal_nodes
    assert loaded.profile_segments == route_profile_segments
    assert loaded.tunnel_slope_i == 0.0022
    assert loaded.tunnel_roughness_n == 0.013
    assert loaded.tunnel_profile_mode == "水力核算模式"
    assert loaded.tunnel_section_type == "圆形"
    assert loaded.tunnel_section_params == {"D": 2.1}
    assert loaded.segment_geometry_source == "generated_tunnel"


def test_get_route_config_returns_route_bucket_after_pipe_entry_removed():
    manager = PressurePipeManager()
    route_longitudinal_nodes = [
        {"chainage": 0.0, "elevation": 420.0, "turn_type": "NONE"},
        {"chainage": 60.0, "elevation": 418.8, "turn_type": "NONE"},
    ]
    manager.from_dict(
        {
            "version": "1.0",
            "last_modified": "",
            "pipes": {
                "flow9-row3": {
                    "name": "9#隧洞",
                    "route_key": "flow9-route1",
                    "route_display_name": "9号整线",
                    "longitudinal_nodes": [],
                }
            },
            "routes": {
                "flow9-route1": {
                    "display_name": "9号整线",
                    "start_row_index": 10,
                    "end_row_index": 10,
                    "longitudinal_nodes": route_longitudinal_nodes,
                    "profile_segments": [{"segment_identity": "flow9-row3"}],
                    "profile_state": "ok",
                }
            },
            "segments": {
                "flow9-row3": {
                    "identity": "flow9-row3",
                    "route_key": "flow9-route1",
                    "route_display_name": "9号整线",
                }
            },
        }
    )

    manager.remove_pipe("flow9-row3")

    snapshot = manager.get_route_config("flow9-route1")
    assert snapshot is not None
    assert snapshot["display_name"] == "9号整线"
    assert snapshot["profile_state"] == "ok"
    assert snapshot["longitudinal_nodes"] == route_longitudinal_nodes
    assert snapshot["profile_segments"] == [{"segment_identity": "flow9-row3"}]
