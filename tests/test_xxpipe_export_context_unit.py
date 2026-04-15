# -*- coding: utf-8 -*-
"""xx管 纵断面主数据拼装测试。"""

from pathlib import Path
import importlib.util
from types import SimpleNamespace

import pytest


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_xxpipe_export_context_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


class _Node(SimpleNamespace):
    def get_structure_type_str(self):
        struct = getattr(self, "structure_type", None)
        if struct is None:
            return ""
        if hasattr(struct, "value"):
            return struct.value
        return str(struct)


def _make_node(
    *,
    ip_no,
    mc,
    structure,
    name,
    flow_section,
    in_out="",
    material="球墨铸铁管",
    diameter=1.2,
    row_identity="",
):
    return _Node(
        ip_number=ip_no,
        station_MC=float(mc),
        station_BC=float(mc),
        station_EC=float(mc),
        turn_angle=0.0,
        structure_type=SimpleNamespace(value=structure),
        name=name,
        flow_section=str(flow_section),
        in_out=SimpleNamespace(value=in_out) if in_out else None,
        is_transition=False,
        is_auto_inserted_channel=False,
        is_pressure_pipe=("有压管道" in structure),
        bottom_elevation=0.0,
        top_elevation=0.0,
        water_level=0.0,
        section_params={"pipe_material": material, "D": diameter},
        pressure_pipe_row_identity=row_identity,
    )


def _build_route_raw_profile_fixture():
    nodes = [
        _make_node(
            ip_no=1,
            mc=100.0,
            structure="有压管道",
            name="赛金压力段",
            flow_section="1",
            in_out="进",
            row_identity="flow1-row1",
        ),
        _make_node(
            ip_no=2,
            mc=120.0,
            structure="有压管道",
            name="赛金压力段",
            flow_section="1",
            row_identity="flow1-row2",
        ),
        _make_node(
            ip_no=3,
            mc=140.0,
            structure="顶管",
            name="赛金压力段",
            flow_section="1",
            in_out="出",
            row_identity="flow1-row3",
        ),
    ]
    engineering_breakpoints = [
        {"chainage": 100.0, "elevation": 410.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 120.0, "elevation": 408.8, "turn_type": "FOLD", "turn_angle": 8.0},
        {"chainage": 140.0, "elevation": 406.2, "turn_type": "NONE", "turn_angle": 0.0},
    ]
    long_map = {
        "flow1-row1": [dict(item) for item in engineering_breakpoints],
        "flow1-row2": [dict(item) for item in engineering_breakpoints],
        "flow1-row3": [dict(item) for item in engineering_breakpoints],
    }
    raw_profile_polyline = [
        (95.0, 410.4),
        (100.0, 410.0),
        (107.0, 409.4),
        (128.0, 407.0),
        (140.0, 406.2),
        (145.0, 405.8),
    ]
    manager_map = {
        "flow1-row1": {
            "segment_geometry_source": "route_raw_profile_polyline",
            "raw_profile_polyline": list(raw_profile_polyline),
        },
        "flow1-row2": {
            "segment_geometry_source": "route_raw_profile_polyline",
            "raw_profile_polyline": list(raw_profile_polyline),
        },
        "flow1-row3": {
            "segment_geometry_source": "route_raw_profile_polyline",
            "raw_profile_polyline": list(raw_profile_polyline),
        },
    }
    warning_context = {
        "flow1-row1": {"identity": "flow1-row1", "route_key": "flow1-route1", "route_display_name": "赛金连续整线"},
        "flow1-row2": {"identity": "flow1-row2", "route_key": "flow1-route1", "route_display_name": "赛金连续整线"},
        "flow1-row3": {"identity": "flow1-row3", "route_key": "flow1-route1", "route_display_name": "赛金连续整线"},
    }
    return nodes, long_map, manager_map, warning_context, raw_profile_polyline


def test_build_xxpipe_profile_data_samples_centerline_and_segments():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="定向钻", name="穿路段", flow_section="1", in_out="进"),
        _make_node(ip_no=2, mc=50.0, structure="定向钻", name="穿路段", flow_section="1"),
        _make_node(ip_no=3, mc=100.0, structure="定向钻", name="穿路段", flow_section="1", in_out="出"),
    ]
    long_map = {
        "1::穿路段": [
            {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
            {"chainage": 100.0, "elevation": 90.0, "turn_type": "无"},
        ]
    }

    data = cad_tools._build_xxpipe_profile_data(nodes, long_map, station_prefix="")

    assert data["centerline_points"] == [
        (0.0, pytest.approx(100.0)),
        (50.0, pytest.approx(95.0)),
        (100.0, pytest.approx(90.0)),
    ]
    assert len(data["centerline_draw_segments"]) == 1
    segment = data["centerline_draw_segments"][0]
    assert segment["identity"] == "1::穿路段"
    assert segment["route_key"] == ""
    assert segment["source_kind"] == "longitudinal_nodes"
    assert segment["start_mc"] == pytest.approx(0.0)
    assert segment["end_mc"] == pytest.approx(100.0)
    assert segment["points"] == [
        (0.0, pytest.approx(100.0)),
        (100.0, pytest.approx(90.0)),
    ]
    assert data["profile_breakpoint_records"] == [
        {
            "identity": "1::穿路段",
            "route_key": "",
            "source_kind": "longitudinal_nodes",
            "chainage": pytest.approx(0.0),
            "elevation": pytest.approx(100.0),
            "turn_type": "无",
            "turn_angle": pytest.approx(0.0),
            "vertical_curve_radius": pytest.approx(0.0),
            "arc_center_s": None,
            "arc_center_z": None,
            "arc_end_chainage": None,
            "arc_theta_rad": None,
        },
        {
            "identity": "1::穿路段",
            "route_key": "",
            "source_kind": "longitudinal_nodes",
            "chainage": pytest.approx(100.0),
            "elevation": pytest.approx(90.0),
            "turn_type": "无",
            "turn_angle": pytest.approx(0.0),
            "vertical_curve_radius": pytest.approx(0.0),
            "arc_center_s": None,
            "arc_center_z": None,
            "arc_end_chainage": None,
            "arc_theta_rad": None,
        },
    ]
    assert [segment["text"] for segment in data["building_segments"]] == ["穿路段"]
    assert [segment["text"] for segment in data["material_segments"]] == ["球墨铸铁管 DN1200"]


def test_build_xxpipe_profile_data_keeps_engineering_breakpoints_separate_from_station_sampling():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="定向钻", name="穿路段", flow_section="1", in_out="进"),
        _make_node(ip_no=2, mc=100.0, structure="定向钻", name="穿路段", flow_section="1", in_out="出"),
    ]
    long_map = {
        "1::穿路段": [
            {"chainage": 0.0, "elevation": 100.0, "turn_type": "NONE", "turn_angle": 0.0, "vertical_curve_radius": 0.0},
            {"chainage": 40.0, "elevation": 96.0, "turn_type": "FOLD", "turn_angle": 12.0, "vertical_curve_radius": 0.0},
            {"chainage": 100.0, "elevation": 90.0, "turn_type": "NONE", "turn_angle": 0.0, "vertical_curve_radius": 0.0},
        ]
    }

    data = cad_tools._build_xxpipe_profile_data(nodes, long_map, station_prefix="")

    assert data["centerline_records"] == [
        {"identity": "1::穿路段", "station_mc": pytest.approx(0.0), "elevation": pytest.approx(100.0)},
        {"identity": "1::穿路段", "station_mc": pytest.approx(100.0), "elevation": pytest.approx(90.0)},
    ]
    assert len(data["centerline_draw_segments"]) == 1
    segment = data["centerline_draw_segments"][0]
    assert segment["identity"] == "1::穿路段"
    assert segment["route_key"] == ""
    assert segment["source_kind"] == "longitudinal_nodes"
    assert segment["start_mc"] == pytest.approx(0.0)
    assert segment["end_mc"] == pytest.approx(100.0)
    assert segment["points"] == [
        (0.0, pytest.approx(100.0)),
        (40.0, pytest.approx(96.0)),
        (100.0, pytest.approx(90.0)),
    ]
    assert [record["chainage"] for record in data["profile_breakpoint_records"]] == pytest.approx([0.0, 40.0, 100.0])
    assert data["profile_breakpoint_records"][1]["turn_type"] == "FOLD"
    assert data["profile_breakpoint_records"][1]["turn_angle"] == pytest.approx(12.0)


def test_build_xxpipe_profile_data_keeps_arc_breakpoints_and_geometry_fields():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="定向钻", name="穿路段", flow_section="1", in_out="进"),
        _make_node(ip_no=2, mc=30.0, structure="定向钻", name="穿路段", flow_section="1", in_out="出"),
    ]
    long_map = {
        "1::穿路段": [
            {"chainage": 0.0, "elevation": 100.0, "turn_type": "NONE", "turn_angle": 0.0},
            {
                "chainage": 10.0,
                "elevation": 90.0,
                "turn_type": "ARC",
                "turn_angle": 18.0,
                "vertical_curve_radius": 10.0,
                "arc_center_s": 10.0,
                "arc_center_z": 100.0,
                "arc_end_chainage": 20.0,
                "arc_theta_rad": 1.5707963267948966,
            },
            {"chainage": 20.0, "elevation": 100.0, "turn_type": "NONE", "turn_angle": 0.0},
            {"chainage": 30.0, "elevation": 110.0, "turn_type": "NONE", "turn_angle": 0.0},
        ]
    }

    data = cad_tools._build_xxpipe_profile_data(nodes, long_map, station_prefix="")

    assert data["centerline_records"] == [
        {"identity": "1::穿路段", "station_mc": pytest.approx(0.0), "elevation": pytest.approx(100.0)},
        {"identity": "1::穿路段", "station_mc": pytest.approx(30.0), "elevation": pytest.approx(110.0)},
    ]
    assert len(data["centerline_draw_segments"]) == 1
    segment = data["centerline_draw_segments"][0]
    assert segment["identity"] == "1::穿路段"
    assert segment["route_key"] == ""
    assert segment["source_kind"] == "longitudinal_nodes"
    assert segment["start_mc"] == pytest.approx(0.0)
    assert segment["end_mc"] == pytest.approx(30.0)
    assert segment["points"][0] == (0.0, pytest.approx(100.0))
    assert segment["points"][1] == (10.0, pytest.approx(90.0))
    assert segment["points"][-2] == (20.0, pytest.approx(100.0))
    assert segment["points"][-1] == (30.0, pytest.approx(110.0))
    assert len(segment["points"]) >= 4
    assert [record["chainage"] for record in data["profile_breakpoint_records"]] == pytest.approx(
        [0.0, 10.0, 20.0, 30.0]
    )
    assert data["profile_breakpoint_records"][1] == {
        "identity": "1::穿路段",
        "route_key": "",
        "source_kind": "longitudinal_nodes",
        "chainage": pytest.approx(10.0),
        "elevation": pytest.approx(90.0),
        "turn_type": "ARC",
        "turn_angle": pytest.approx(18.0),
        "vertical_curve_radius": pytest.approx(10.0),
        "arc_center_s": pytest.approx(10.0),
        "arc_center_z": pytest.approx(100.0),
        "arc_end_chainage": pytest.approx(20.0),
        "arc_theta_rad": pytest.approx(1.5707963267948966),
    }


def test_build_xxpipe_profile_data_keeps_station_sampling_and_engineering_breakpoints_when_route_raw_profile_exists():
    nodes, long_map, manager_map, warning_context, _raw_profile_polyline = _build_route_raw_profile_fixture()

    data = cad_tools._build_xxpipe_profile_data(
        nodes,
        long_map,
        station_prefix="",
        manager_config_by_identity=manager_map,
        warning_context_by_identity=warning_context,
    )

    assert data["centerline_records"] == [
        {"identity": "flow1-row1", "station_mc": pytest.approx(100.0), "elevation": pytest.approx(410.0)},
        {"identity": "flow1-row2", "station_mc": pytest.approx(120.0), "elevation": pytest.approx(408.8)},
        {"identity": "flow1-row3", "station_mc": pytest.approx(140.0), "elevation": pytest.approx(406.2)},
    ]
    assert len(data["centerline_draw_segments"]) == 1
    segment = data["centerline_draw_segments"][0]
    assert segment["route_key"] == "flow1-route1"
    assert segment["source_kind"] == "route_raw_profile_polyline"
    assert segment["start_mc"] == pytest.approx(100.0)
    assert segment["end_mc"] == pytest.approx(140.0)
    assert segment["points"] == [
        (100.0, pytest.approx(410.0)),
        (107.0, pytest.approx(409.4)),
        (128.0, pytest.approx(407.0)),
        (140.0, pytest.approx(406.2)),
    ]
    assert [record["chainage"] for record in data["profile_breakpoint_records"]] == pytest.approx([100.0, 120.0, 140.0])
    assert [record["elevation"] for record in data["profile_breakpoint_records"]] == pytest.approx([410.0, 408.8, 406.2])


def test_build_xxpipe_profile_data_rejects_unallowed_structure():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠段", flow_section="1"),
        _make_node(ip_no=2, mc=50.0, structure="明渠-矩形", name="明渠段", flow_section="1"),
    ]
    long_map = {
        "1::明渠段": [
            {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
            {"chainage": 50.0, "elevation": 99.0, "turn_type": "无"},
        ]
    }

    with pytest.raises(ValueError, match="明渠-矩形"):
        cad_tools._build_xxpipe_profile_data(nodes, long_map, station_prefix="")


@pytest.mark.parametrize("structure", ["暗涵-矩形", "暗涵-圆拱直墙型"])
def test_build_xxpipe_profile_data_rejects_culvert_family_from_lower_table(structure):
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure=structure, name="暗涵段", flow_section="1"),
        _make_node(ip_no=2, mc=50.0, structure=structure, name="暗涵段", flow_section="1"),
    ]
    long_map = {
        "1::暗涵段": [
            {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
            {"chainage": 50.0, "elevation": 99.0, "turn_type": "无"},
        ]
    }

    with pytest.raises(ValueError, match=structure):
        cad_tools._build_xxpipe_profile_data(nodes, long_map, station_prefix="")


def test_build_xxpipe_profile_data_treats_single_point_longitudinal_nodes_as_missing_axis():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="定向钻", name="穿路段", flow_section="1", in_out="进"),
        _make_node(ip_no=2, mc=50.0, structure="定向钻", name="穿路段", flow_section="1", in_out="出"),
    ]
    long_map = {
        "1::穿路段": [
            {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
        ]
    }

    with pytest.raises(ValueError) as exc_info:
        cad_tools._build_xxpipe_profile_data(nodes, long_map, station_prefix="")

    message = str(exc_info.value)
    assert "缺少轴线纵断面" in message
    assert "至少需要 2 个纵断面节点" not in message


def test_build_xxpipe_profile_data_uses_same_station_identity_candidates_when_representative_identity_misses():
    named = _make_node(
        ip_no=1,
        mc=0.0,
        structure="定向钻",
        name="穿路段",
        flow_section="1",
        in_out="进",
    )
    named.bottom_elevation = 10.0
    named.top_elevation = 11.0
    named.water_level = 10.5

    anchor = _make_node(
        ip_no=2,
        mc=0.0,
        structure="有压管道",
        name="",
        flow_section="1",
        row_identity="flow1-row1",
    )

    data = cad_tools._build_xxpipe_profile_data(
        [named, anchor],
        {
            "flow1-row1": [
                {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
                {"chainage": 100.0, "elevation": 90.0, "turn_type": "无"},
            ]
        },
        station_prefix="",
    )

    assert data["centerline_points"] == [(0.0, pytest.approx(100.0))]
    assert [record["identity"] for record in data["centerline_records"]] == ["flow1-row1"]


def test_make_xxpipe_identity_from_node_prefers_pressure_pipe_row_identity_for_unnamed_segment():
    node = _make_node(
        ip_no=1,
        mc=20.0,
        structure="有压管道",
        name="",
        flow_section="2",
        row_identity="flow2-row6",
    )

    assert cad_tools._make_xxpipe_identity_from_node(node) == "flow2-row6"


def test_build_xxpipe_identity_rows_keeps_multiple_unnamed_segments_separate():
    nodes = [
        _make_node(
            ip_no=1,
            mc=0.0,
            structure="有压管道",
            name="",
            flow_section="2",
            row_identity="flow2-row6",
        ),
        _make_node(
            ip_no=2,
            mc=50.0,
            structure="有压管道",
            name="",
            flow_section="2",
            row_identity="flow2-row7",
        ),
    ]

    rows = cad_tools._build_xxpipe_identity_rows(nodes)

    assert [row["identity"] for row in rows] == ["flow2-row6", "flow2-row7"]


def test_build_xxpipe_profile_data_uses_row_identity_for_multiple_unnamed_segments():
    nodes = [
        _make_node(
            ip_no=1,
            mc=0.0,
            structure="有压管道",
            name="",
            flow_section="2",
            row_identity="flow2-row6",
            material="钢管",
            diameter=1.0,
        ),
        _make_node(
            ip_no=2,
            mc=50.0,
            structure="有压管道",
            name="",
            flow_section="2",
            row_identity="flow2-row7",
            material="球墨铸铁管",
            diameter=1.2,
        ),
    ]
    long_map = {
        "flow2-row6": [
            {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
            {"chainage": 20.0, "elevation": 98.0, "turn_type": "无"},
        ],
        "flow2-row7": [
            {"chainage": 40.0, "elevation": 96.0, "turn_type": "无"},
            {"chainage": 60.0, "elevation": 94.0, "turn_type": "无"},
        ],
    }

    data = cad_tools._build_xxpipe_profile_data(nodes, long_map, station_prefix="")

    assert [record["identity"] for record in data["centerline_records"]] == ["flow2-row6", "flow2-row7"]
    assert [segment["identity"] for segment in data["material_segments"]] == ["flow2-row6", "flow2-row7"]
    assert [segment["text"] for segment in data["material_segments"]] == ["钢管 DN1000", "球墨铸铁管 DN1200"]


def test_build_xxpipe_profile_data_merges_continuous_plain_pressure_pipe_material_segments():
    nodes = [
        _make_node(
            ip_no=1,
            mc=0.0,
            structure="有压管道",
            name="",
            flow_section="2",
            row_identity="flow2-row6",
            material="HDPE管",
            diameter=0.4,
        ),
        _make_node(
            ip_no=2,
            mc=50.0,
            structure="有压管道",
            name="",
            flow_section="2",
            row_identity="flow2-row7",
            material="HDPE管",
            diameter=0.4,
        ),
        _make_node(
            ip_no=3,
            mc=100.0,
            structure="有压管道",
            name="",
            flow_section="2",
            row_identity="flow2-row8",
            material="HDPE管",
            diameter=0.4,
        ),
    ]
    long_map = {
        "flow2-row6": [
            {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
            {"chainage": 20.0, "elevation": 98.0, "turn_type": "无"},
        ],
        "flow2-row7": [
            {"chainage": 40.0, "elevation": 96.0, "turn_type": "无"},
            {"chainage": 60.0, "elevation": 94.0, "turn_type": "无"},
        ],
        "flow2-row8": [
            {"chainage": 80.0, "elevation": 92.0, "turn_type": "无"},
            {"chainage": 100.0, "elevation": 90.0, "turn_type": "无"},
        ],
    }

    data = cad_tools._build_xxpipe_profile_data(nodes, long_map, station_prefix="")

    assert [record["identity"] for record in data["centerline_records"]] == [
        "flow2-row6",
        "flow2-row7",
        "flow2-row8",
    ]
    assert data["material_segments"] == [
        {
            "text": "HDPE管 DN400",
            "identity": "flow2-row6",
            "start_mc": 0.0,
            "end_mc": 100.0,
            "mid_mc": 50.0,
            "merge_mode": "plain_pressure_pipe",
            "flow_section_key": "2",
        }
    ]


def test_build_xxpipe_profile_data_breaks_plain_pipe_material_segments_at_directional_drill_and_flow_section():
    nodes = [
        _make_node(
            ip_no=1,
            mc=0.0,
            structure="有压管道",
            name="",
            flow_section="2",
            row_identity="flow2-row6",
            material="HDPE管",
            diameter=0.4,
        ),
        _make_node(
            ip_no=2,
            mc=50.0,
            structure="有压管道",
            name="",
            flow_section="2",
            row_identity="flow2-row7",
            material="HDPE管",
            diameter=0.4,
        ),
        _make_node(
            ip_no=3,
            mc=100.0,
            structure="定向钻",
            name="穿路段",
            flow_section="2",
            material="钢管",
            diameter=0.5,
        ),
        _make_node(
            ip_no=4,
            mc=150.0,
            structure="定向钻",
            name="穿路段",
            flow_section="2",
            material="钢管",
            diameter=0.5,
        ),
        _make_node(
            ip_no=5,
            mc=200.0,
            structure="有压管道",
            name="",
            flow_section="3",
            row_identity="flow3-row8",
            material="HDPE管",
            diameter=0.4,
        ),
        _make_node(
            ip_no=6,
            mc=250.0,
            structure="有压管道",
            name="",
            flow_section="3",
            row_identity="flow3-row9",
            material="HDPE管",
            diameter=0.4,
        ),
    ]
    long_map = {
        "flow2-row6": [
            {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
            {"chainage": 20.0, "elevation": 98.0, "turn_type": "无"},
        ],
        "flow2-row7": [
            {"chainage": 40.0, "elevation": 96.0, "turn_type": "无"},
            {"chainage": 60.0, "elevation": 94.0, "turn_type": "无"},
        ],
        "2::穿路段": [
            {"chainage": 100.0, "elevation": 92.0, "turn_type": "无"},
            {"chainage": 150.0, "elevation": 88.0, "turn_type": "无"},
        ],
        "flow3-row8": [
            {"chainage": 180.0, "elevation": 87.0, "turn_type": "无"},
            {"chainage": 220.0, "elevation": 85.0, "turn_type": "无"},
        ],
        "flow3-row9": [
            {"chainage": 240.0, "elevation": 84.0, "turn_type": "无"},
            {"chainage": 260.0, "elevation": 82.0, "turn_type": "无"},
        ],
    }

    data = cad_tools._build_xxpipe_profile_data(nodes, long_map, station_prefix="")

    assert [segment["text"] for segment in data["building_segments"]] == ["穿路段"]
    assert data["material_segments"] == [
        {
            "text": "HDPE管 DN400",
            "identity": "flow2-row6",
            "start_mc": 0.0,
            "end_mc": 50.0,
            "mid_mc": 25.0,
            "merge_mode": "plain_pressure_pipe",
            "flow_section_key": "2",
        },
        {
            "text": "钢管 DN500",
            "identity": "2::穿路段",
            "start_mc": 100.0,
            "end_mc": 150.0,
            "mid_mc": 125.0,
            "merge_mode": "named_structure",
            "flow_section_key": "2",
        },
        {
            "text": "HDPE管 DN400",
            "identity": "flow3-row8",
            "start_mc": 200.0,
            "end_mc": 250.0,
            "mid_mc": 225.0,
            "merge_mode": "plain_pressure_pipe",
            "flow_section_key": "3",
        },
    ]
