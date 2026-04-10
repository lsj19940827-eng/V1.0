# -*- coding: utf-8 -*-
"""xx管 纵断面导出分支测试。"""

from pathlib import Path
import importlib.util
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace

import pytest


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location(
        "cad_tools_xxpipe_longitudinal_export_test_mod",
        matches[0],
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


def _load_panel_class():
    helper_path = Path(__file__).with_name("test_pressure_pipe_export_longitudinal_nodes_unit.py")
    spec = importlib.util.spec_from_file_location(
        "panel_longitudinal_nodes_helper_mod_for_xxpipe",
        helper_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._load_panel_class()


class _Node(SimpleNamespace):
    def get_structure_type_str(self):
        struct = getattr(self, "structure_type", None)
        if struct is None:
            return ""
        if hasattr(struct, "value"):
            return struct.value
        return str(struct)


class _TextEntity:
    def __init__(self, msp, text, dxfattribs):
        self._msp = msp
        self._text = text
        self._dxfattribs = dict(dxfattribs or {})

    def set_placement(self, point, align=None):
        self._msp.text_records.append(
            {
                "text": self._text,
                "x": float(point[0]),
                "y": float(point[1]),
                "align": align,
                "dxfattribs": dict(self._dxfattribs),
            }
        )
        return self


class _DummyMSP:
    def __init__(self):
        self.text_records = []
        self.line_records = []
        self.polyline_records = []

    def add_line(self, start, end, **_kwargs):
        self.line_records.append(
            {
                "start": (float(start[0]), float(start[1])),
                "end": (float(end[0]), float(end[1])),
            }
        )
        return None

    def add_lwpolyline(self, points, dxfattribs=None):
        self.polyline_records.append(
            {
                "points": [(float(x), float(y)) for x, y in points],
                "layer": (dxfattribs or {}).get("layer", ""),
            }
        )
        return None

    def add_text(self, text, dxfattribs=None):
        return _TextEntity(self, text, dxfattribs)


def _count_line(records, start, end, tol=1e-6):
    count = 0
    for rec in records:
        if (
            abs(rec["start"][0] - start[0]) <= tol
            and abs(rec["start"][1] - start[1]) <= tol
            and abs(rec["end"][0] - end[0]) <= tol
            and abs(rec["end"][1] - end[1]) <= tol
        ):
            count += 1
    return count


class _ProjSettings:
    def __init__(self, prefix):
        self._prefix = prefix

    def get_station_prefix(self):
        return self._prefix


class _Panel:
    def __init__(self, prefix):
        self._prefix = prefix

    def _build_settings(self):
        return _ProjSettings(self._prefix)

    def window(self):
        return None


def _make_node(
    *,
    ip_no,
    mc,
    structure="定向钻",
    name="穿路段",
    flow_section="1",
    in_out="",
    material="球墨铸铁管",
    diameter=1.2,
    row_identity="",
    bottom_elevation=0.0,
):
    return _Node(
        station_MC=float(mc),
        station_BC=float(mc),
        station_EC=float(mc),
        bottom_elevation=float(bottom_elevation),
        top_elevation=0.0,
        water_level=0.0,
        structure_type=SimpleNamespace(value=structure),
        in_out=SimpleNamespace(value=in_out) if in_out else None,
        is_transition=False,
        is_auto_inserted_channel=False,
        is_inverted_siphon=False,
        is_pressure_pipe=structure in {"有压管道", "定向钻", "顶管"},
        name=name,
        flow_section=flow_section,
        ip_number=int(ip_no),
        turn_angle=0.0,
        section_params={"pipe_material": material, "D": diameter},
        pressure_pipe_row_identity=row_identity,
    )


def _sample_nodes():
    return [
        _make_node(ip_no=1, mc=0.0, in_out="进"),
        _make_node(ip_no=2, mc=50.0),
        _make_node(ip_no=3, mc=100.0, in_out="出"),
    ]


def _sample_xxqu_mixed_nodes():
    open_channel = _make_node(
        ip_no=1,
        mc=0.0,
        structure="明渠-圆形",
        name="渠道段",
        bottom_elevation=100.0,
    )
    pressure_pipe = _make_node(
        ip_no=2,
        mc=100.0,
        structure="有压管道",
        name="苟家湾",
        in_out="进",
        row_identity="flow1-row2",
    )
    auto_inserted = _make_node(
        ip_no=3,
        mc=110.0,
        structure="有压管道",
        name="自动补点",
        row_identity="flow1-row3",
    )
    auto_inserted.is_auto_inserted_channel = True
    directional_drill = _make_node(
        ip_no=4,
        mc=120.0,
        structure="定向钻",
        name="大石包",
    )
    return [open_channel, pressure_pipe, auto_inserted, directional_drill], [pressure_pipe, directional_drill]


def _scaled_settings():
    return {
        "text_height": 3.5,
        "rotation": 90,
        "elev_decimals": 3,
        "xxpipe_centerline_elev_decimals": 2,
        "xxpipe_station_decimals": 2,
        "y_line_height": 120,
        "scale_x": 2000,
        "scale_y": 1000,
    }


def _sample_profile_data():
    nodes = _sample_nodes()
    data = cad_tools._build_xxpipe_profile_data(
        nodes,
        {
            "1::穿路段": [
                {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
                {"chainage": 100.0, "elevation": 90.0, "turn_type": "无"},
            ]
        },
        station_prefix="",
    )
    return nodes, data


def _mixed_tail_nodes():
    return [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠1", bottom_elevation=410.0),
        _make_node(ip_no=2, mc=50.0, structure="明渠-矩形", name="明渠2", bottom_elevation=409.2),
        _make_node(ip_no=3, mc=100.0, structure="明渠-矩形", name="明渠3", bottom_elevation=408.4),
        _make_node(ip_no=4, mc=150.0, structure="有压管道", name="末端压力管", in_out="进", bottom_elevation=407.5),
        _make_node(ip_no=5, mc=200.0, structure="有压管道", name="末端压力管", bottom_elevation=406.7),
        _make_node(ip_no=6, mc=250.0, structure="有压管道", name="末端压力管", in_out="出", bottom_elevation=405.9),
    ]


def _mixed_tail_nodes_with_duplicate_channel_start():
    duplicate_start = _make_node(
        ip_no=10,
        mc=0.0,
        structure="明渠-矩形",
        name="明渠起点占位",
        bottom_elevation=0.0,
    )
    duplicate_start.top_elevation = 0.0
    duplicate_start.water_level = 0.0
    return [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠1", bottom_elevation=410.0),
        duplicate_start,
        _make_node(ip_no=2, mc=50.0, structure="明渠-矩形", name="明渠2", bottom_elevation=409.2),
        _make_node(ip_no=3, mc=100.0, structure="明渠-矩形", name="明渠3", bottom_elevation=408.4),
        _make_node(ip_no=4, mc=150.0, structure="有压管道", name="末端压力管", in_out="进", bottom_elevation=407.5),
        _make_node(ip_no=5, mc=200.0, structure="有压管道", name="末端压力管", bottom_elevation=406.7),
        _make_node(ip_no=6, mc=250.0, structure="有压管道", name="末端压力管", in_out="出", bottom_elevation=405.9),
    ]


def _build_route_level_tail_profile_data():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    route_nodes = [
        {"chainage": 120.0, "elevation": 100.0, "turn_type": "NONE"},
        {"chainage": 160.0, "elevation": 96.0, "turn_type": "NONE"},
        {"chainage": 200.0, "elevation": 92.0, "turn_type": "NONE"},
    ]
    tail_nodes = [
        _make_node(
            ip_no=4,
            mc=120.0,
            structure="有压管道",
            name="末端压力管",
            in_out="进",
            material="钢管",
            diameter=0.8,
            row_identity="1::末端压力管",
            bottom_elevation=407.5,
        ),
        _make_node(
            ip_no=5,
            mc=160.0,
            structure="有压管道",
            name="末端压力管",
            material="钢管",
            diameter=0.8,
            row_identity="1::末端压力管",
            bottom_elevation=406.7,
        ),
        _make_node(
            ip_no=6,
            mc=200.0,
            structure="有压管道",
            name="末端压力管",
            in_out="出",
            material="钢管",
            diameter=0.8,
            row_identity="1::末端压力管",
            bottom_elevation=405.9,
        ),
    ]
    group = SimpleNamespace(
        storage_key="1::末端压力管",
        route_key="flow1-route1",
        route_display_name="末端整线",
        display_name="末端压力管",
        name="末端压力管",
        identity="1::末端压力管",
        flow_section="1",
        segment_start_mc=120.0,
        segment_end_mc=200.0,
    )
    panel.calculated_nodes = tail_nodes
    panel._build_nodes_from_table = lambda: tail_nodes
    panel._build_settings = lambda: _ProjSettings("")
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支渠")
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda _key: None,
        to_dict=lambda: {
            "routes": {
                "flow1-route1": {
                    "display_name": "末端整线",
                    "longitudinal_nodes": list(route_nodes),
                    "profile_segments": [
                        {
                            "segment_identity": "1::末端压力管",
                            "source_kind": "non_tunnel_dxf",
                            "start_mc": 120.0,
                            "end_mc": 200.0,
                            "longitudinal_nodes": [
                                {"chainage": 120.0, "elevation": 100.0, "turn_type": "NONE"},
                            ],
                        }
                    ],
                }
            }
        },
    )
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: [group]
    profile_data = cad_tools._build_panel_xxpipe_profile_data(panel, tail_nodes, station_prefix="")
    return tail_nodes, profile_data


def _build_leading_gap_tail_profile_data():
    tail_nodes = [
        _make_node(
            ip_no=3,
            mc=1950.37,
            structure="有压管道",
            name="",
            flow_section="1",
            material="球墨铸铁管",
            diameter=0.6,
            row_identity="flow1-row3",
            bottom_elevation=345.674,
        ),
        _make_node(
            ip_no=4,
            mc=1981.787,
            structure="有压管道",
            name="",
            flow_section="1",
            material="球墨铸铁管",
            diameter=0.6,
            row_identity="flow1-row4",
            bottom_elevation=345.674,
        ),
        _make_node(
            ip_no=5,
            mc=2003.336,
            structure="有压管道",
            name="",
            flow_section="1",
            material="球墨铸铁管",
            diameter=0.6,
            row_identity="flow1-row5",
            bottom_elevation=348.401,
        ),
    ]
    xxpipe_profile_data = {
        "profile_text_nodes": list(tail_nodes),
        "ip_records": [],
        "centerline_points": [
            (1981.787, 347.0276),
            (2003.336, 348.4010),
        ],
        "centerline_records": [
            {"identity": "flow1-row4", "station_mc": 1981.787, "elevation": 347.0276},
            {"identity": "flow1-row5", "station_mc": 2003.336, "elevation": 348.4010},
        ],
        "building_segments": [],
        "material_segments": [],
        "warnings": {
            "allow_partial_export": True,
            "missing_axis_identities": [],
            "missing_axis_details": [],
            "uncovered_stations": [
                {
                    "identity": "flow1-row3",
                    "station_mc": 1950.37,
                    "station_text": "蒲支1+950.37",
                }
            ],
        },
    }
    return tail_nodes, xxpipe_profile_data


def test_build_xxpipe_profile_row_layout_ignores_oversized_y_line_height():
    settings = {**_scaled_settings(), "y_line_height": 180}

    _, enabled_ids, _row_layout, total_height, line_height, boundaries = cad_tools._build_xxpipe_profile_row_layout(
        settings
    )

    assert enabled_ids == [
        "building_name",
        "ip_name",
        "station",
        "centerline_elev",
        "pipe_material",
    ]
    assert total_height < settings["y_line_height"]
    assert line_height == total_height
    assert boundaries[-1] == total_height
    assert all(value <= total_height for value in boundaries)


def test_resolve_tail_pressure_split_context_returns_channel_and_tail_nodes(monkeypatch):
    nodes = _mixed_tail_nodes()
    captured = {}

    def _fake_build_profile_data(panel, part_nodes, station_prefix="", **kwargs):
        _ = (panel, station_prefix)
        captured["tail_nodes"] = list(part_nodes)
        captured["lookup_nodes"] = list(kwargs.get("lookup_nodes") or [])
        return {"profile_text_nodes": list(part_nodes)}

    monkeypatch.setattr(
        cad_tools,
        "_build_panel_xxpipe_profile_data",
        _fake_build_profile_data,
    )

    context = cad_tools._resolve_tail_pressure_split_context(_Panel(""), nodes, station_prefix="")

    assert context is not None
    assert [node.station_MC for node in context["channel_nodes"]] == pytest.approx([0.0, 50.0, 100.0])
    assert [node.station_MC for node in context["tail_nodes"]] == pytest.approx([150.0, 200.0, 250.0])
    assert [node.station_MC for node in captured["tail_nodes"]] == pytest.approx([150.0, 200.0, 250.0])
    assert [node.station_MC for node in captured["lookup_nodes"]] == pytest.approx([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])


def test_resolve_tail_pressure_split_context_returns_none_when_pressure_not_at_tail(monkeypatch):
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠1", bottom_elevation=410.0),
        _make_node(ip_no=2, mc=50.0, structure="有压管道", name="中段压力管", bottom_elevation=409.0),
        _make_node(ip_no=3, mc=100.0, structure="明渠-矩形", name="明渠2", bottom_elevation=408.0),
    ]
    called = {"value": False}

    def _unexpected_build(*_args, **_kwargs):
        called["value"] = True
        return {}

    monkeypatch.setattr(cad_tools, "_build_panel_xxpipe_profile_data", _unexpected_build)

    context = cad_tools._resolve_tail_pressure_split_context(_Panel(""), nodes, station_prefix="")

    assert context is None
    assert called["value"] is False


def test_resolve_tail_pressure_split_context_keeps_adjacent_plain_tunnel_in_channel_table(monkeypatch):
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠1", bottom_elevation=410.0),
        _make_node(ip_no=2, mc=40.0, structure="隧洞-圆拱直墙型", name="前段隧洞", bottom_elevation=409.5),
        _make_node(ip_no=3, mc=80.0, structure="明渠-矩形", name="明渠2", bottom_elevation=409.0),
        _make_node(ip_no=4, mc=120.0, structure="隧洞-圆拱直墙型", name="末段隧洞", bottom_elevation=408.5),
        _make_node(ip_no=5, mc=160.0, structure="有压管道", name="末端压力管", in_out="进", bottom_elevation=408.0),
        _make_node(ip_no=6, mc=200.0, structure="有压管道", name="末端压力管", in_out="出", bottom_elevation=407.2),
    ]
    captured = {}

    def _fake_build_profile_data(panel, part_nodes, station_prefix="", **kwargs):
        _ = (panel, station_prefix)
        captured["tail_nodes"] = list(part_nodes)
        captured["lookup_nodes"] = list(kwargs.get("lookup_nodes") or [])
        return {"profile_text_nodes": list(part_nodes)}

    monkeypatch.setattr(
        cad_tools,
        "_build_panel_xxpipe_profile_data",
        _fake_build_profile_data,
    )

    context = cad_tools._resolve_tail_pressure_split_context(_Panel(""), nodes, station_prefix="")

    assert context is not None
    assert [node.station_MC for node in context["channel_nodes"]] == pytest.approx([0.0, 40.0, 80.0, 120.0])
    assert [node.station_MC for node in context["tail_nodes"]] == pytest.approx([160.0, 200.0])
    assert [node.station_MC for node in captured["tail_nodes"]] == pytest.approx([160.0, 200.0])
    assert [node.station_MC for node in captured["lookup_nodes"]] == pytest.approx([0.0, 40.0, 80.0, 120.0, 160.0, 200.0])


def test_build_panel_xxpipe_profile_data_tail_split_lookup_nodes_restore_centerline_records():
    channel_nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠1", bottom_elevation=410.0),
        _make_node(ip_no=2, mc=50.0, structure="明渠-矩形", name="明渠2", bottom_elevation=409.2),
        _make_node(
            ip_no=3,
            mc=100.0,
            structure="隧洞-圆形",
            name="猴子山隧洞",
            in_out="出",
            row_identity="flow1-row10",
            bottom_elevation=408.8,
        ),
    ]
    tail_nodes = [
        _make_node(
            ip_no=4,
            mc=150.0,
            structure="有压管道",
            name="末端压力管",
            in_out="进",
            row_identity="flow1-row11",
            bottom_elevation=407.5,
        ),
        _make_node(
            ip_no=5,
            mc=200.0,
            structure="有压管道",
            name="末端压力管",
            in_out="出",
            row_identity="flow1-row12",
            bottom_elevation=405.9,
        ),
    ]
    all_nodes = channel_nodes + tail_nodes
    captured_identities = []

    panel = _Panel("")
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支渠")
    panel.get_pressure_pipe_longitudinal_nodes_for_export = lambda rows=None: (
        captured_identities.append([str((row or {}).get("identity", "") or "") for row in (rows or [])])
        or (
            {
                "flow1-row11": [
                    {"chainage": 100.0, "elevation": 100.0, "turn_type": "无"},
                    {"chainage": 200.0, "elevation": 90.0, "turn_type": "无"},
                ],
                "flow1-row12": [
                    {"chainage": 100.0, "elevation": 100.0, "turn_type": "无"},
                    {"chainage": 200.0, "elevation": 90.0, "turn_type": "无"},
                ],
            }
            if any(identity == "flow1-row10" for identity in captured_identities[-1])
            else {}
        )
    )
    panel._pressure_pipe_manager = SimpleNamespace(to_dict=lambda: {"pipes": {}})

    without_lookup = cad_tools._build_panel_xxpipe_profile_data(
        panel,
        tail_nodes,
        station_prefix="",
    )
    with_lookup = cad_tools._build_panel_xxpipe_profile_data(
        panel,
        tail_nodes,
        station_prefix="",
        lookup_nodes=all_nodes,
    )

    assert without_lookup["centerline_records"] == []
    assert [record["identity"] for record in with_lookup["centerline_records"]] == ["flow1-row11", "flow1-row12"]
    assert [record["station_mc"] for record in with_lookup["centerline_records"]] == pytest.approx([150.0, 200.0])
    assert [record["elevation"] for record in with_lookup["centerline_records"]] == pytest.approx([95.0, 90.0])
    assert any("flow1-row10" in identities for identities in captured_identities)


def test_build_panel_xxpipe_profile_data_uses_panel_table_nodes_as_default_lookup_source():
    channel_nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠1", bottom_elevation=410.0),
        _make_node(ip_no=2, mc=50.0, structure="明渠-矩形", name="明渠2", bottom_elevation=409.2),
        _make_node(
            ip_no=3,
            mc=100.0,
            structure="隧洞-圆形",
            name="猴子山隧洞",
            in_out="出",
            row_identity="flow1-row10",
            bottom_elevation=408.8,
        ),
    ]
    tail_nodes = [
        _make_node(
            ip_no=4,
            mc=150.0,
            structure="有压管道",
            name="末端压力管",
            in_out="进",
            row_identity="flow1-row11",
            bottom_elevation=407.1,
        ),
        _make_node(
            ip_no=5,
            mc=200.0,
            structure="有压管道",
            name="末端压力管",
            in_out="出",
            row_identity="flow1-row12",
            bottom_elevation=405.9,
        ),
    ]
    all_nodes = channel_nodes + tail_nodes
    captured_identities = []

    panel = _Panel("")
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支渠")
    panel._build_nodes_from_table = lambda: list(all_nodes)
    panel.get_pressure_pipe_longitudinal_nodes_for_export = lambda rows=None: (
        captured_identities.append([str((row or {}).get("identity", "") or "") for row in (rows or [])])
        or (
            {
                "flow1-row11": [
                    {"chainage": 100.0, "elevation": 100.0, "turn_type": "无"},
                    {"chainage": 200.0, "elevation": 90.0, "turn_type": "无"},
                ],
                "flow1-row12": [
                    {"chainage": 100.0, "elevation": 100.0, "turn_type": "无"},
                    {"chainage": 200.0, "elevation": 90.0, "turn_type": "无"},
                ],
            }
            if any(identity == "flow1-row10" for identity in captured_identities[-1])
            else {}
        )
    )
    panel._pressure_pipe_manager = SimpleNamespace(to_dict=lambda: {"pipes": {}})

    result = cad_tools._build_panel_xxpipe_profile_data(
        panel,
        tail_nodes,
        station_prefix="",
    )

    assert [record["identity"] for record in result["centerline_records"]] == ["flow1-row11", "flow1-row12"]
    assert any("flow1-row10" in identities for identities in captured_identities)


def test_build_panel_xxpipe_profile_data_passes_route_metadata_into_lookup_rows(monkeypatch):
    nodes = [
        _make_node(
            ip_no=73,
            mc=3968.95,
            structure="有压管道",
            name="苟家湾",
            in_out="进",
            row_identity="flow1-row73",
        )
    ]
    captured = {}

    panel = _Panel("赛支")
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支渠")
    panel._prepare_pressure_pipe_dialog_context = lambda current_nodes, settings=None, show_xxpipe_warning=False: {
        "xxpipe_route_mode": True,
        "route_import_targets": {
            "flow1-route1": {
                "display_name": "赛金连续整线",
                "targets": [
                    {
                        "row_index": 0,
                        "label": "苟家湾有压管道进",
                        "station_mc": 3968.95,
                    }
                ],
                "nodes": list(current_nodes),
            }
        },
    }
    panel.get_pressure_pipe_longitudinal_nodes_for_export = lambda rows=None: (
        captured.setdefault("rows", [dict(row) for row in (rows or [])]) or {}
    )
    panel._pressure_pipe_manager = SimpleNamespace(to_dict=lambda: {"pipes": {}})

    monkeypatch.setattr(
        cad_tools,
        "_build_xxpipe_profile_data",
        lambda *_a, **_k: {
            "profile_text_nodes": list(nodes),
            "centerline_records": [],
            "centerline_points": [],
            "ip_records": [],
            "building_segments": [],
            "material_segments": [],
            "warnings": {
                "allow_partial_export": True,
                "missing_axis_identities": [],
                "uncovered_stations": [],
            },
        },
    )

    cad_tools._build_panel_xxpipe_profile_data(
        panel,
        nodes,
        station_prefix="赛支",
        lookup_nodes=nodes,
    )

    assert captured["rows"] == [
        {
            "name": "苟家湾",
            "flow_section": "1",
            "identity": "flow1-row73",
            "route_key": "flow1-route1",
            "route_display_name": "赛金连续整线",
            "node_label": "苟家湾有压管道进",
            "station_mc": 3968.95,
            "station_text": "赛支3+968.95",
            "is_tunnel": False,
        }
    ]


def test_resolve_tail_pressure_split_context_keeps_post_pressure_tunnel_in_lower_table(monkeypatch):
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠1", bottom_elevation=410.0),
        _make_node(ip_no=2, mc=40.0, structure="隧洞-圆拱直墙型", name="前段隧洞", bottom_elevation=409.5),
        _make_node(ip_no=3, mc=80.0, structure="有压管道", name="压力段1", in_out="进", bottom_elevation=409.0),
        _make_node(ip_no=4, mc=120.0, structure="隧洞-圆拱直墙型", name="交错隧洞", bottom_elevation=408.6),
        _make_node(ip_no=5, mc=160.0, structure="顶管", name="压力段2", in_out="出", bottom_elevation=408.1),
    ]
    captured = {}

    def _capture_build(_panel, part_nodes, station_prefix="", **_kwargs):
        captured["tail_nodes"] = list(part_nodes)
        captured["station_prefix"] = station_prefix
        return {}

    monkeypatch.setattr(cad_tools, "_build_panel_xxpipe_profile_data", _capture_build)

    context = cad_tools._resolve_tail_pressure_split_context(_Panel(""), nodes, station_prefix="")

    assert context is not None
    assert [node.station_MC for node in context["channel_nodes"]] == pytest.approx([0.0, 40.0])
    assert [node.station_MC for node in context["tail_nodes"]] == pytest.approx([80.0, 120.0, 160.0])
    assert [node.station_MC for node in captured["tail_nodes"]] == pytest.approx([80.0, 120.0, 160.0])


def test_plan_tail_pressure_split_uses_full_nodes_and_keeps_tunnel_side_correct():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠1", bottom_elevation=410.0),
        _make_node(ip_no=2, mc=40.0, structure="隧洞-圆拱直墙型", name="前段隧洞", bottom_elevation=409.5),
        _make_node(ip_no=3, mc=80.0, structure="有压管道", name="苟家湾", in_out="进", bottom_elevation=409.0),
        _make_node(ip_no=4, mc=120.0, structure="定向钻", name="大石包", bottom_elevation=408.6),
        _make_node(ip_no=5, mc=160.0, structure="隧洞-圆拱直墙型", name="后段隧洞", bottom_elevation=408.1),
        _make_node(ip_no=6, mc=200.0, structure="有压管道", name="苟家湾", in_out="出", bottom_elevation=407.8),
    ]

    plan = cad_tools.plan_tail_pressure_split(nodes)

    assert plan is not None
    assert [node.station_MC for node in plan["channel_nodes"]] == pytest.approx([0.0, 40.0])
    assert [node.station_MC for node in plan["channel_valid_nodes"]] == pytest.approx([0.0, 40.0])
    assert [node.station_MC for node in plan["tail_nodes"]] == pytest.approx([80.0, 120.0, 160.0, 200.0])
    assert [node.station_MC for node in plan["tail_lookup_nodes"]] == pytest.approx([0.0, 40.0, 80.0, 120.0, 160.0, 200.0])
    assert plan["tail_export_mode"] == "xxpipe"


def test_plan_tail_pressure_split_returns_none_for_pretrimmed_route_nodes():
    route_nodes = [
        _make_node(ip_no=3, mc=80.0, structure="有压管道", name="苟家湾", in_out="进", bottom_elevation=409.0),
        _make_node(ip_no=4, mc=120.0, structure="定向钻", name="大石包", bottom_elevation=408.6),
        _make_node(ip_no=5, mc=160.0, structure="隧洞-圆拱直墙型", name="后段隧洞", bottom_elevation=408.1),
        _make_node(ip_no=6, mc=200.0, structure="有压管道", name="苟家湾", in_out="出", bottom_elevation=407.8),
    ]

    assert cad_tools.plan_tail_pressure_split(route_nodes) is None


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[1]
    base_dir = root / ".pytest_tmp" / "xxpipe_longitudinal_export_unit"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(dir=base_dir))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _parse_polyline_vertex_cmds(path):
    pat = re.compile(r"^pl\s+([-\d.eE]+),([-\d.eE]+)\s*$")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        rows.append((float(m.group(1)), float(m.group(2))))
    return rows


def _parse_pl_line_cmds(path):
    pat = re.compile(
        r"^pl\s+([-\d.eE]+),([-\d.eE]+)\s+([-\d.eE]+),([-\d.eE]+)\s*$"
    )
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        rows.append(
            {
                "start": (float(m.group(1)), float(m.group(2))),
                "end": (float(m.group(3)), float(m.group(4))),
            }
        )
    return rows


def _scaled_m_to_mm(value_m, scale_denom):
    return float(value_m) * 1000.0 / float(scale_denom)


def _has_vertical_line_at_x(records, x_value, tol=1e-6):
    for rec in records:
        x0, y0 = rec["start"]
        x1, y1 = rec["end"]
        if abs(x0 - x1) > tol:
            continue
        if abs(x0 - x_value) > tol:
            continue
        if abs(y0 - y1) <= tol:
            continue
        return True
    return False


def _get_vertical_line_segments_at_x(records, x_value, tol=1e-6):
    segments = []
    for rec in records:
        x0, y0 = rec["start"]
        x1, y1 = rec["end"]
        if abs(x0 - x1) > tol:
            continue
        if abs(x0 - x_value) > tol:
            continue
        if abs(y0 - y1) <= tol:
            continue
        segments.append((min(y0, y1), max(y0, y1)))
    return segments


def _sample_adjacent_special_profile_data(structure_name):
    nodes = [
        _make_node(
            ip_no=14,
            mc=850.0,
            structure="有压管道",
            name="",
            flow_section="2",
            material="HDPE管",
            diameter=0.4,
            row_identity="flow2-row14",
        ),
        _make_node(
            ip_no=15,
            mc=900.0,
            structure="有压管道",
            name="",
            flow_section="2",
            material="HDPE管",
            diameter=0.4,
            row_identity="flow2-row15",
        ),
        _make_node(
            ip_no=16,
            mc=950.0,
            structure=structure_name,
            name="观音岩",
            flow_section="2",
            in_out="进",
            material="钢管",
            diameter=0.5,
        ),
        _make_node(
            ip_no=17,
            mc=1000.0,
            structure=structure_name,
            name="观音岩",
            flow_section="2",
            in_out="出",
            material="钢管",
            diameter=0.5,
        ),
        _make_node(
            ip_no=18,
            mc=1050.0,
            structure="有压管道",
            name="",
            flow_section="2",
            material="HDPE管",
            diameter=0.4,
            row_identity="flow2-row18",
        ),
        _make_node(
            ip_no=19,
            mc=1100.0,
            structure="有压管道",
            name="",
            flow_section="2",
            material="HDPE管",
            diameter=0.4,
            row_identity="flow2-row19",
        ),
    ]
    long_map = {
        "flow2-row14": [
            {"chainage": 840.0, "elevation": 100.0, "turn_type": "无"},
            {"chainage": 860.0, "elevation": 99.0, "turn_type": "无"},
        ],
        "flow2-row15": [
            {"chainage": 890.0, "elevation": 98.0, "turn_type": "无"},
            {"chainage": 910.0, "elevation": 97.0, "turn_type": "无"},
        ],
        "2::观音岩": [
            {"chainage": 950.0, "elevation": 96.0, "turn_type": "无"},
            {"chainage": 1000.0, "elevation": 92.0, "turn_type": "无"},
        ],
        "flow2-row18": [
            {"chainage": 1040.0, "elevation": 91.0, "turn_type": "无"},
            {"chainage": 1060.0, "elevation": 90.0, "turn_type": "无"},
        ],
        "flow2-row19": [
            {"chainage": 1090.0, "elevation": 89.0, "turn_type": "无"},
            {"chainage": 1110.0, "elevation": 88.0, "turn_type": "无"},
        ],
    }
    profile_data = cad_tools._build_xxpipe_profile_data(
        nodes,
        long_map,
        station_prefix="",
    )
    return nodes, profile_data


def test_draw_profile_on_msp_in_xxpipe_mode_uses_centerline_polyline_only(monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    nodes, profile_data = _sample_profile_data()
    msp = _DummyMSP()

    cad_tools._draw_profile_on_msp(
        msp,
        nodes,
        nodes,
        _scaled_settings(),
        station_prefix="",
        export_mode="xxpipe",
        xxpipe_profile_data=profile_data,
    )

    assert [rec["layer"] for rec in msp.polyline_records] == ["管中心线"]

    texts = [rec["text"] for rec in msp.text_records]
    assert "建筑物名称" in texts
    assert "IP点名称" in texts
    assert "里程桩号" in texts
    assert "（千米+米）" in texts
    assert "管中心线高程（米）" in texts
    assert "管材（管径）" in texts
    assert "穿路段" in texts
    assert "球墨铸铁管 DN1200" in texts
    assert "0+000.00" in texts
    assert "0+050.00" in texts
    assert "0+100.00" in texts
    assert "95.00" in texts
    assert "95.000" not in texts


def test_export_longitudinal_txt_to_path_in_xxpipe_mode_writes_fixed_rows(local_tmp_path, monkeypatch):
    nodes, profile_data = _sample_profile_data()
    out_file = local_tmp_path / "xxpipe_longitudinal_profile.txt"

    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)

    cad_tools._export_longitudinal_txt_to_path(
        _Panel(""),
        nodes,
        nodes,
        _scaled_settings(),
        str(out_file),
        export_mode="xxpipe",
        xxpipe_profile_data=profile_data,
    )

    content = out_file.read_text(encoding="utf-8")
    assert "管中心线高程（米）" in content
    assert "球墨铸铁管 DN1200" in content
    assert "穿路段" in content
    assert "渠底高程" not in content
    assert "设计水位" not in content
    assert "0+000.00" in content
    assert "0+050.00" in content
    assert "0+100.00" in content
    assert "95.00" in content
    assert "95.000" not in content

    assert _parse_polyline_vertex_cmds(out_file) == pytest.approx(
        [
            (0.0, 100.0),
            (25.0, 95.0),
            (50.0, 90.0),
        ]
    )


def test_xxpipe_export_respects_custom_centerline_decimal_precision(local_tmp_path, monkeypatch):
    nodes, profile_data = _sample_profile_data()
    out_file = local_tmp_path / "xxpipe_longitudinal_profile_three_decimals.txt"
    settings = {**_scaled_settings(), "xxpipe_centerline_elev_decimals": 3}

    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)

    cad_tools._export_longitudinal_txt_to_path(
        _Panel(""),
        nodes,
        nodes,
        settings,
        str(out_file),
        export_mode="xxpipe",
        xxpipe_profile_data=profile_data,
    )

    content = out_file.read_text(encoding="utf-8")
    assert "95.000" in content


def test_xxpipe_export_respects_custom_station_decimal_precision(local_tmp_path, monkeypatch):
    nodes, profile_data = _sample_profile_data()
    out_file = local_tmp_path / "xxpipe_longitudinal_profile_station_three_decimals.txt"
    settings = {**_scaled_settings(), "xxpipe_station_decimals": 3}

    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)

    cad_tools._export_longitudinal_txt_to_path(
        _Panel(""),
        nodes,
        nodes,
        settings,
        str(out_file),
        export_mode="xxpipe",
        xxpipe_profile_data=profile_data,
    )

    content = out_file.read_text(encoding="utf-8")
    assert "0+050.000" in content


@pytest.mark.parametrize("structure_name", ["定向钻", "顶管"])
def test_collect_xxpipe_full_height_boundaries_ignores_outer_adjacent_plain_pipe_nodes(structure_name):
    _nodes, profile_data = _sample_adjacent_special_profile_data(structure_name)

    assert cad_tools._collect_xxpipe_full_height_boundary_mcs(profile_data) == pytest.approx(
        [850.0, 950.0, 1000.0, 1100.0]
    )


def test_collect_xxpipe_full_height_boundaries_use_visible_tail_bounds_when_first_centerline_missing():
    _tail_nodes, profile_data = _build_leading_gap_tail_profile_data()

    assert cad_tools._collect_xxpipe_full_height_boundary_mcs(profile_data) == pytest.approx(
        [1950.37, 2003.336]
    )


@pytest.mark.parametrize("structure_name", ["定向钻", "顶管"])
def test_draw_profile_on_msp_keeps_lower_half_vlines_for_outer_adjacent_plain_pipe_nodes(
    monkeypatch, structure_name
):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    nodes, profile_data = _sample_adjacent_special_profile_data(structure_name)
    msp = _DummyMSP()

    cad_tools._draw_profile_on_msp(
        msp,
        nodes,
        nodes,
        _scaled_settings(),
        station_prefix="",
        export_mode="xxpipe",
        xxpipe_profile_data=profile_data,
    )

    scale_x = _scaled_settings()["scale_x"]
    _settings, _enabled_ids, row_layout, _total_height, _line_height, _boundaries = cad_tools._build_xxpipe_profile_row_layout(
        _scaled_settings()
    )
    expected_top = row_layout["ip_name"]["top"]
    for mc in (900.0, 1050.0):
        segments = _get_vertical_line_segments_at_x(
            msp.line_records,
            _scaled_m_to_mm(mc, scale_x),
        )
        assert segments == pytest.approx([(0.0, expected_top)])
    for mc in (850.0, 950.0, 1000.0, 1100.0):
        assert _has_vertical_line_at_x(msp.line_records, _scaled_m_to_mm(mc, scale_x))


@pytest.mark.parametrize("structure_name", ["定向钻", "顶管"])
def test_export_longitudinal_txt_keeps_lower_half_vlines_for_outer_adjacent_plain_pipe_nodes(
    local_tmp_path, monkeypatch, structure_name
):
    nodes, profile_data = _sample_adjacent_special_profile_data(structure_name)
    out_file = local_tmp_path / f"xxpipe_outer_vline_{structure_name}.txt"

    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)

    cad_tools._export_longitudinal_txt_to_path(
        _Panel(""),
        nodes,
        nodes,
        _scaled_settings(),
        str(out_file),
        export_mode="xxpipe",
        xxpipe_profile_data=profile_data,
    )

    records = _parse_pl_line_cmds(out_file)
    scale_x = _scaled_settings()["scale_x"]
    _settings, _enabled_ids, row_layout, _total_height, _line_height, _boundaries = cad_tools._build_xxpipe_profile_row_layout(
        _scaled_settings()
    )
    expected_top = row_layout["ip_name"]["top"]
    for mc in (900.0, 1050.0):
        segments = _get_vertical_line_segments_at_x(
            records,
            _scaled_m_to_mm(mc, scale_x),
        )
        assert segments == pytest.approx([(0.0, expected_top)])
    for mc in (850.0, 950.0, 1000.0, 1100.0):
        assert _has_vertical_line_at_x(records, _scaled_m_to_mm(mc, scale_x))


@pytest.mark.parametrize(
    ("func_name", "expected_mode"),
    [
        ("export_longitudinal_profile_txt", "xxpipe"),
        ("export_longitudinal_profile_dxf", "xxpipe"),
    ],
)
def test_xxpipe_export_entries_open_dialog_in_xxpipe_mode(monkeypatch, func_name, expected_mode):
    captured = {}
    nodes = _sample_nodes()

    class _Dialog:
        def __init__(self, *args, **kwargs):
            captured["mode"] = kwargs.get("mode")
            self.result = None

        def exec(self):
            return cad_tools.QDialog.Rejected

    panel = SimpleNamespace(
        calculated_nodes=list(nodes),
        _text_export_settings={},
    )
    panel.window = lambda: None

    monkeypatch.setattr(cad_tools, "MODELS_AVAILABLE", True)
    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "_resolve_xxpipe_export_source_nodes", lambda *_a, **_k: list(nodes))
    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _Dialog)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)

    getattr(cad_tools, func_name)(panel)

    assert captured["mode"] == expected_mode


@pytest.mark.parametrize(
    ("func_name", "suffix"),
    [
        ("export_longitudinal_profile_txt", ".txt"),
        ("export_longitudinal_profile_dxf", ".dxf"),
    ],
)
def test_xxpipe_export_entries_use_filtered_route_nodes_in_xxqu_route_mode(
    local_tmp_path,
    monkeypatch,
    func_name,
    suffix,
):
    mixed_nodes, route_nodes = _sample_xxqu_mixed_nodes()
    out_file = local_tmp_path / f"xxqu_filtered_route{suffix}"
    captured = {}

    class _Dialog:
        def __init__(self, *_args, **_kwargs):
            self.result = {}

        def exec(self):
            return cad_tools.QDialog.Accepted

    panel = SimpleNamespace(
        calculated_nodes=list(mixed_nodes),
        _text_export_settings={},
        channel_name_edit=SimpleNamespace(text=lambda: "赛金"),
        channel_level_combo=SimpleNamespace(currentText=lambda: "支渠"),
    )
    panel.window = lambda: None
    panel._build_nodes_from_table = lambda: list(mixed_nodes)
    panel._build_settings = lambda: _ProjSettings("")
    panel._prepare_pressure_pipe_dialog_context = lambda nodes, settings=None, show_xxpipe_warning=False: {
        "xxpipe_route_mode": True,
        "route_import_targets": {
            "flow1-route2": {
                "nodes": [nodes[3], nodes[2]],
                "targets": [{"row_index": 3}, {"row_index": 2}],
            },
            "flow1-route1": {
                "nodes": [nodes[1], nodes[1]],
                "targets": [{"row_index": 1}, {"row_index": 1}],
            },
        },
    }

    monkeypatch.setattr(cad_tools, "MODELS_AVAILABLE", True)
    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "plan_tail_pressure_split", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _Dialog)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(
        cad_tools.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_a, **_k: (str(out_file), "TXT" if suffix == ".txt" else "DXF")),
    )

    if func_name == "export_longitudinal_profile_txt":
        monkeypatch.setattr(
            cad_tools,
            "_export_longitudinal_txt_to_path",
            lambda _panel, nodes, valid_nodes, *_a, **_k: captured.update(
                {"nodes": list(nodes), "valid_nodes": list(valid_nodes)}
            ),
        )
    else:
        docs = {}

        class _FakeDoc:
            def __init__(self):
                self.saved_path = None
                self._msp = object()

            def modelspace(self):
                return self._msp

            def saveas(self, path):
                self.saved_path = path

        def _fake_new(_version):
            doc = _FakeDoc()
            docs["doc"] = doc
            return doc

        monkeypatch.setitem(sys.modules, "ezdxf", SimpleNamespace(new=_fake_new))
        monkeypatch.setattr(cad_tools, "_setup_profile_dxf_document", lambda *_a, **_k: None)
        monkeypatch.setattr(cad_tools, "_ensure_profile_layers", lambda *_a, **_k: None)
        monkeypatch.setattr(
            cad_tools,
            "_build_panel_xxpipe_profile_data",
            lambda _panel, nodes, **_k: captured.update({"nodes": list(nodes)}) or {"profile_text_nodes": list(nodes)},
        )
        monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", lambda *_a, **_k: (120.0, 80.0))

    getattr(cad_tools, func_name)(panel)

    assert captured["nodes"] == route_nodes
    if func_name == "export_longitudinal_profile_txt":
        assert captured["valid_nodes"] == route_nodes


def test_build_xxpipe_partial_export_notice_prompts_clear_then_reimport_for_uncovered_cache():
    notice = cad_tools._build_xxpipe_partial_export_notice(
        {
            "warnings": {
                "allow_partial_export": True,
                "missing_axis_identities": [],
                "uncovered_stations": [
                    {"identity": "1::三清庙", "station_mc": 80.0, "station_text": "1+000.000"}
                ],
            },
        }
    )

    assert "清空后重新导入" in notice
    assert "1::三清庙@1+000.000" in notice


def test_build_xxpipe_partial_export_notice_describes_identity_mismatch_as_partial_blank():
    notice = cad_tools._build_xxpipe_partial_export_notice(
        {
            "warnings": {
                "allow_partial_export": True,
                "missing_axis_identities": ["flow1-row73"],
                "missing_axis_details": [
                    {
                        "identity": "flow1-row73",
                        "kind": "identity_mismatch",
                        "station_text": "赛支3+968.95",
                        "node_label": "苟家湾有压管道进",
                        "route_display_name": "赛金连续整线",
                    }
                ],
                "uncovered_stations": [],
            },
        }
    )

    assert "已导入纵断面DXF" in notice
    assert "个别节点未匹配" in notice
    assert "赛支3+968.95" in notice
    assert "苟家湾有压管道进" in notice
    assert "flow1-row73" not in notice


def test_build_xxpipe_profile_data_supports_tunnel_structures_with_bottom_elevation_and_section_text():
    nodes = [
        _make_node(
            ip_no=1,
            mc=0.0,
            structure="隧洞-圆形",
            name="穿山段",
            in_out="进",
            material="隧洞",
            diameter=2.4,
            bottom_elevation=98.2,
        ),
        _make_node(
            ip_no=2,
            mc=50.0,
            structure="隧洞-圆形",
            name="穿山段",
            material="隧洞",
            diameter=2.4,
            bottom_elevation=93.7,
        ),
        _make_node(
            ip_no=3,
            mc=100.0,
            structure="隧洞-圆形",
            name="穿山段",
            in_out="出",
            material="隧洞",
            diameter=2.4,
            bottom_elevation=89.1,
        ),
    ]
    data = cad_tools._build_xxpipe_profile_data(
        nodes,
        {
            "1::穿山段": [
                {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
                {"chainage": 100.0, "elevation": 90.0, "turn_type": "无"},
            ]
        },
        station_prefix="",
    )

    assert [record["elevation"] for record in data["centerline_records"]] == pytest.approx([98.2, 93.7, 89.1])
    assert [segment["text"] for segment in data["building_segments"]] == ["穿山段"]
    assert [segment["text"] for segment in data["material_segments"]] == ["圆形隧洞 D=2.4m"]


def test_format_xxpipe_profile_section_text_supports_arch_and_horseshoe_tunnel_labels():
    arch_node = _make_node(
        ip_no=1,
        mc=0.0,
        structure="隧洞-圆形",
        material="隧洞",
        diameter=0.0,
    )
    arch_node.section_params = {}
    horseshoe_node = _make_node(
        ip_no=1,
        mc=0.0,
        structure="隧洞-圆形",
        material="隧洞",
        diameter=0.0,
    )
    horseshoe_node.section_params = {}

    arch_text = cad_tools._format_xxpipe_profile_section_text(
        arch_node,
        "隧洞-圆形",
        {
            "tunnel_section_type": "圆拱直墙型隧洞",
            "tunnel_section_params": {"B": 3.2, "H": 4.5},
        },
    )
    horseshoe_text = cad_tools._format_xxpipe_profile_section_text(
        horseshoe_node,
        "隧洞-圆形",
        {
            "tunnel_section_type": "马蹄形Ⅰ型隧洞",
            "tunnel_section_params": {"R": 1.8},
        },
    )

    assert arch_text == "圆拱直墙型隧洞 B/H=3.2/4.5m"
    assert horseshoe_text == "马蹄形Ⅰ型隧洞 r=1.8m"


def test_resolve_xxpipe_profile_elevation_prefers_generated_tunnel_profile_from_manager():
    node = _make_node(
        ip_no=1,
        mc=0.0,
        structure="隧洞-圆形",
        material="隧洞",
        diameter=2.4,
        bottom_elevation=98.2,
    )

    sampled = cad_tools._resolve_xxpipe_profile_elevation(
        node,
        96.4,
        manager_row={
            "segment_geometry_source": "generated_tunnel",
            "tunnel_invert_inlet": 96.8,
            "tunnel_slope_i": 0.01,
        },
    )

    assert sampled == pytest.approx(96.4)


def test_build_xxpipe_profile_data_uses_plan_distance_station_fallback():
    start = _make_node(ip_no=1, mc=0.0, in_out="进")
    middle = _make_node(ip_no=2, mc=50.0)
    end = _make_node(ip_no=3, mc=100.0, in_out="出")
    middle.station_MC = None
    start.x, start.y = 0.0, 0.0
    middle.x, middle.y = 30.0, 40.0
    end.x, end.y = 60.0, 80.0
    nodes = [start, middle, end]

    data = cad_tools._build_xxpipe_profile_data(
        nodes,
        {
            "1::穿路段": [
                {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
                {"chainage": 100.0, "elevation": 90.0, "turn_type": "无"},
            ]
        },
        station_prefix="",
    )

    assert [record["station_mc"] for record in data["centerline_records"]] == pytest.approx([0.0, 50.0, 100.0])
    assert [record["elevation"] for record in data["centerline_records"]] == pytest.approx([100.0, 95.0, 90.0])


def test_build_xxpipe_profile_data_uses_distance_fallback_without_any_station_anchor():
    start = _make_node(ip_no=1, mc=0.0, structure="有压管道", in_out="进")
    middle = _make_node(ip_no=2, mc=0.0, structure="有压管道")
    end = _make_node(ip_no=3, mc=0.0, structure="有压管道", in_out="出")
    start.station_MC = None
    middle.station_MC = None
    end.station_MC = None
    start.x, start.y = 0.0, 0.0
    middle.x, middle.y = 30.0, 0.0
    end.x, end.y = 60.0, 0.0
    nodes = [start, middle, end]

    data = cad_tools._build_xxpipe_profile_data(
        nodes,
        {
            "1::穿路段": [
                {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
                {"chainage": 60.0, "elevation": 94.0, "turn_type": "无"},
            ]
        },
        station_prefix="",
    )

    assert [record["station_mc"] for record in data["centerline_records"]] == pytest.approx([0.0, 30.0, 60.0])
    assert [record["elevation"] for record in data["centerline_records"]] == pytest.approx([100.0, 97.0, 94.0])


def test_build_xxpipe_profile_data_relaxes_missing_axis_for_continuous_xxqu():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="定向钻", name="穿路段", in_out="进"),
        _make_node(ip_no=2, mc=50.0, structure="定向钻", name="穿路段"),
        _make_node(ip_no=3, mc=100.0, structure="定向钻", name="穿路段", in_out="出"),
    ]

    data = cad_tools._build_xxpipe_profile_data(
        nodes,
        {},
        station_prefix="",
        export_policy={
            "allow_partial_export": True,
        },
    )

    assert data["centerline_records"] == []
    assert data["warnings"]["allow_partial_export"] is True
    assert data["warnings"]["missing_axis_identities"]


def test_build_xxpipe_profile_data_reports_detailed_coverage_gap_in_strict_mode():
    nodes = [
        _make_node(
            ip_no=1,
            mc=0.0,
            structure="有压管道",
            name="南干支线",
            in_out="进",
            row_identity="flow1-row1",
        ),
        _make_node(
            ip_no=2,
            mc=80.0,
            structure="有压管道",
            name="南干支线",
            in_out="出",
            row_identity="flow1-row2",
        ),
    ]
    longitudinal_nodes = [
        {"chainage": 0.0, "elevation": 420.0, "turn_type": "NONE"},
        {"chainage": 50.0, "elevation": 418.0, "turn_type": "NONE"},
    ]

    with pytest.raises(ValueError, match="导入失败：纵断面范围不够") as exc_info:
        cad_tools._build_xxpipe_profile_data(
            nodes,
            {
                "flow1-row1": list(longitudinal_nodes),
                "flow1-row2": list(longitudinal_nodes),
            },
            station_prefix="T",
            warning_context_by_identity={
                "flow1-row1": {
                    "identity": "flow1-row1",
                    "route_display_name": "流量段1 整线1",
                    "node_label": "IP1",
                    "station_text": "T0+000.000",
                },
                "flow1-row2": {
                    "identity": "flow1-row2",
                    "route_display_name": "流量段1 整线1",
                    "node_label": "IP2",
                    "station_text": "T0+080.000",
                },
            },
        )

    message = str(exc_info.value)
    assert "流量段1 整线1" in message
    assert "导入失败：纵断面范围不够" in message
    assert "这条整线需要覆盖到桩号 80.000 m" in message
    assert "当前导入的纵断面只到 50.000 m" in message
    assert "允许的 1.0 mm 误差" in message
    assert "未覆盖节点：IP2@T0+080.000" in message


def test_build_panel_xxpipe_profile_data_skips_tunnel_missing_axis_warning_in_route_mode():
    nodes = [
        _make_node(
            ip_no=1,
            mc=0.0,
            structure="隧洞-圆拱直墙型",
            name="交错隧洞",
            row_identity="flow1-row1",
        ),
        _make_node(
            ip_no=2,
            mc=80.0,
            structure="有压管道",
            name="压力段1",
            in_out="进",
            row_identity="flow1-row2",
        ),
        _make_node(
            ip_no=3,
            mc=120.0,
            structure="顶管",
            name="压力段2",
            in_out="出",
            row_identity="flow1-row3",
        ),
    ]
    longitudinal_nodes = [
        {"chainage": 80.0, "elevation": 420.0, "turn_type": "NONE"},
        {"chainage": 120.0, "elevation": 418.0, "turn_type": "NONE"},
    ]
    panel = _Panel("T")
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支渠")
    panel.calculated_nodes = list(nodes)
    panel._build_nodes_from_table = lambda: list(nodes)
    panel._prepare_pressure_pipe_dialog_context = lambda *_a, **_k: {
        "xxpipe_route_mode": True,
        "route_import_targets": {
            "flow1-route1": {
                "display_name": "流量段1 整线1",
                "station_prefix": "T",
                "targets": [
                    {"row_index": 0, "label": "IP1", "station_mc": 0.0},
                    {"row_index": 1, "label": "IP2", "station_mc": 80.0},
                    {"row_index": 2, "label": "IP3", "station_mc": 120.0},
                ],
                "nodes": list(nodes),
            }
        },
    }
    panel.get_pressure_pipe_longitudinal_nodes_for_export = lambda rows=None: {
        "flow1-row2": list(longitudinal_nodes),
        "flow1-row3": list(longitudinal_nodes),
    }
    panel._pressure_pipe_manager = SimpleNamespace(to_dict=lambda: {"pipes": {}})

    data = cad_tools._build_panel_xxpipe_profile_data(panel, nodes, station_prefix="T")

    assert data["warnings"]["missing_axis_identities"] == []
    assert data["warnings"]["uncovered_stations"] == []
    assert [record["identity"] for record in data["centerline_records"]] == [
        "flow1-row2",
        "flow1-row3",
    ]


def test_build_panel_xxpipe_profile_data_skips_tunnel_identity_mismatch_in_strict_mixed_route():
    nodes = [
        _make_node(
            ip_no=1,
            mc=0.0,
            structure="隧洞-圆拱直墙型",
            name="交错隧洞",
            row_identity="flow1-row1",
        ),
        _make_node(
            ip_no=2,
            mc=80.0,
            structure="有压管道",
            name="压力段1",
            in_out="进",
            row_identity="flow1-row2",
        ),
        _make_node(
            ip_no=3,
            mc=120.0,
            structure="顶管",
            name="压力段2",
            in_out="出",
            row_identity="flow1-row3",
        ),
    ]
    longitudinal_nodes = [
        {"chainage": 80.0, "elevation": 420.0, "turn_type": "NONE"},
        {"chainage": 120.0, "elevation": 418.0, "turn_type": "NONE"},
    ]
    panel = _Panel("T")
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支管")
    panel.calculated_nodes = list(nodes)
    panel._build_nodes_from_table = lambda: list(nodes)
    panel._prepare_pressure_pipe_dialog_context = lambda *_a, **_k: {
        "xxpipe_route_mode": True,
        "route_import_targets": {
            "flow1-route1": {
                "display_name": "流量段1 整线1",
                "station_prefix": "T",
                "targets": [
                    {"row_index": 0, "label": "IP1", "station_mc": 0.0},
                    {"row_index": 1, "label": "IP2", "station_mc": 80.0},
                    {"row_index": 2, "label": "IP3", "station_mc": 120.0},
                ],
                "nodes": list(nodes),
            }
        },
    }
    panel.get_pressure_pipe_longitudinal_nodes_for_export = lambda rows=None: {
        "flow1-row2": list(longitudinal_nodes),
        "flow1-row3": list(longitudinal_nodes),
    }
    panel._pressure_pipe_manager = SimpleNamespace(to_dict=lambda: {"pipes": {}})

    data = cad_tools._build_panel_xxpipe_profile_data(panel, nodes, station_prefix="T")

    assert data["warnings"]["missing_axis_identities"] == []
    assert data["warnings"]["uncovered_stations"] == []
    assert [record["identity"] for record in data["centerline_records"]] == [
        "flow1-row2",
        "flow1-row3",
    ]


def test_build_xxpipe_profile_data_skips_same_name_tunnel_identity_checks_without_route_mode():
    nodes = [
        _make_node(
            ip_no=17,
            mc=2200.0,
            structure="隧洞-圆拱直墙型",
            name="罗家湾",
            row_identity="",
        ),
        _make_node(
            ip_no=18,
            mc=2300.0,
            structure="隧洞-圆拱直墙型",
            name="罗家湾",
            row_identity="",
        ),
        _make_node(
            ip_no=19,
            mc=2739.785,
            structure="有压管道",
            name="蒲支压力段",
            in_out="进",
            row_identity="flow1-row19",
        ),
    ]
    longitudinal_nodes = {
        "flow1-row19": [
            {"chainage": 2739.785, "elevation": 348.401, "turn_type": "NONE"},
            {"chainage": 6526.755, "elevation": 325.770, "turn_type": "NONE"},
        ]
    }

    data = cad_tools._build_xxpipe_profile_data(
        nodes,
        longitudinal_nodes,
        station_prefix="蒲支",
        export_policy={"allow_partial_export": False},
    )

    assert data["warnings"]["missing_axis_identities"] == []
    assert data["warnings"]["uncovered_stations"] == []
    assert [record["identity"] for record in data["centerline_records"]] == ["flow1-row19"]


def test_build_panel_xxpipe_profile_data_skips_tunnel_identity_mismatch_in_strict_lookup_rows_mode():
    nodes = [
        _make_node(
            ip_no=1,
            mc=0.0,
            structure="隧洞-圆拱直墙型",
            name="罗家湾",
            flow_section="1",
            row_identity="",
        ),
        _make_node(
            ip_no=2,
            mc=20.0,
            structure="隧洞-圆拱直墙型",
            name="罗家湾",
            flow_section="1",
            row_identity="",
        ),
        _make_node(
            ip_no=3,
            mc=80.0,
            structure="有压管道",
            name="压力段1",
            in_out="进",
            row_identity="flow1-row2",
        ),
        _make_node(
            ip_no=4,
            mc=120.0,
            structure="顶管",
            name="压力段2",
            in_out="出",
            row_identity="flow1-row3",
        ),
    ]
    longitudinal_nodes = [
        {"chainage": 80.0, "elevation": 420.0, "turn_type": "NONE"},
        {"chainage": 120.0, "elevation": 418.0, "turn_type": "NONE"},
    ]
    panel = _Panel("T")
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支管")
    panel.calculated_nodes = list(nodes)
    panel._build_nodes_from_table = lambda: list(nodes)
    panel.get_pressure_pipe_longitudinal_nodes_for_export = lambda rows=None: {
        "flow1-row2": list(longitudinal_nodes),
        "flow1-row3": list(longitudinal_nodes),
    }
    panel._pressure_pipe_manager = SimpleNamespace(to_dict=lambda: {"pipes": {}})

    data = cad_tools._build_panel_xxpipe_profile_data(
        panel,
        nodes,
        station_prefix="T",
        lookup_rows=[
            {
                "name": "罗家湾",
                "flow_section": "1",
                "identity": "1::罗家湾",
                "route_key": "flow1-route1",
                "route_display_name": "流量段1 整线1",
                "node_label": "IP1",
                "station_text": "T0+000.000",
                "station_mc": 0.0,
                "is_tunnel_structure": True,
            },
            {
                "name": "压力段1",
                "flow_section": "1",
                "identity": "flow1-row2",
                "route_key": "flow1-route1",
                "route_display_name": "流量段1 整线1",
                "node_label": "IP3",
                "station_text": "T0+080.000",
                "station_mc": 80.0,
            },
            {
                "name": "压力段2",
                "flow_section": "1",
                "identity": "flow1-row3",
                "route_key": "flow1-route1",
                "route_display_name": "流量段1 整线1",
                "node_label": "IP4",
                "station_text": "T0+120.000",
                "station_mc": 120.0,
            },
        ],
    )

    assert data["warnings"]["missing_axis_identities"] == []
    assert data["warnings"]["uncovered_stations"] == []
    assert [record["identity"] for record in data["centerline_records"]] == [
        "flow1-row2",
        "flow1-row3",
    ]


def test_export_xxpipe_longitudinal_txt_to_path_shows_guidance_for_relaxed_xxqu(local_tmp_path, monkeypatch):
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="有压管道", name="南干支线", in_out="进"),
        _make_node(ip_no=2, mc=50.0, structure="有压管道", name="南干支线"),
        _make_node(ip_no=3, mc=100.0, structure="有压管道", name="南干支线", in_out="出"),
    ]
    out_file = local_tmp_path / "relaxed_xxqu_profile.txt"
    infos = []
    profile_data = cad_tools._build_xxpipe_profile_data(
        nodes,
        {},
        station_prefix="",
        export_policy={
            "allow_partial_export": True,
            "show_plain_pipe_name": True,
        },
    )

    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **_k: infos.append(args))
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)

    cad_tools._export_xxpipe_longitudinal_txt_to_path(
        _Panel(""),
        nodes,
        _scaled_settings(),
        str(out_file),
        station_prefix="",
        xxpipe_profile_data=profile_data,
    )

    assert out_file.exists()
    assert any("导入纵断面轴线DXF" in args[2] for args in infos)


@pytest.mark.parametrize(
    ("building_name", "expected_text"),
    [
        ("南干支线", "南干支线"),
        ("", "有压管道"),
    ],
)
def test_build_xxpipe_profile_data_uses_relaxed_plain_pipe_building_name_rules(
    building_name,
    expected_text,
):
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="有压管道", name=building_name, in_out="进"),
        _make_node(ip_no=2, mc=50.0, structure="有压管道", name=building_name),
        _make_node(ip_no=3, mc=100.0, structure="有压管道", name=building_name, in_out="出"),
    ]

    data = cad_tools._build_xxpipe_profile_data(
        nodes,
        {},
        station_prefix="",
        export_policy={
            "allow_partial_export": True,
            "show_plain_pipe_name": True,
        },
    )

    assert [segment["text"] for segment in data["building_segments"]] == [expected_text]


def test_build_xxpipe_profile_data_merges_saijin_building_name_segments_for_centered_labels():
    nodes = [
        _make_node(
            ip_no=73,
            mc=3968.95,
            structure="有压管道",
            name="苟家湾",
            in_out="进",
            row_identity="flow1-row73",
        ),
        _make_node(
            ip_no=74,
            mc=3971.87,
            structure="定向钻",
            name="大石包",
            in_out="进",
            row_identity="flow1-row74",
        ),
        _make_node(
            ip_no=75,
            mc=4366.58,
            structure="定向钻",
            name="大石包",
            in_out="出",
            row_identity="flow1-row75",
        ),
        _make_node(
            ip_no=76,
            mc=4431.26,
            structure="有压管道",
            name="苟家湾",
            in_out="进",
            row_identity="flow1-row76",
        ),
        _make_node(
            ip_no=77,
            mc=4693.42,
            structure="有压管道",
            name="苟家湾",
            in_out="出",
            row_identity="flow1-row77",
        ),
    ]

    data = cad_tools._build_xxpipe_profile_data(
        nodes,
        {},
        station_prefix="赛支",
        export_policy={
            "allow_partial_export": True,
            "show_plain_pipe_name": True,
        },
    )

    assert [segment["text"] for segment in data["building_segments"]] == [
        "苟家湾",
        "大石包",
        "苟家湾",
    ]
    assert data["building_segments"][1]["start_mc"] == pytest.approx(3971.87)
    assert data["building_segments"][1]["end_mc"] == pytest.approx(4366.58)
    assert data["building_segments"][1]["mid_mc"] == pytest.approx((3971.87 + 4366.58) / 2.0)


def test_build_xxpipe_profile_data_merges_saijin_named_structure_material_segment_once():
    nodes = [
        _make_node(
            ip_no=73,
            mc=3968.95,
            structure="有压管道",
            name="苟家湾",
            in_out="进",
            row_identity="flow1-row73",
        ),
        _make_node(
            ip_no=74,
            mc=3971.87,
            structure="定向钻",
            name="大石包",
            in_out="进",
            row_identity="flow1-row74",
        ),
        _make_node(
            ip_no=75,
            mc=4366.58,
            structure="定向钻",
            name="大石包",
            in_out="出",
            row_identity="flow1-row75",
        ),
        _make_node(
            ip_no=76,
            mc=4431.26,
            structure="有压管道",
            name="苟家湾",
            in_out="进",
            row_identity="flow1-row76",
        ),
        _make_node(
            ip_no=77,
            mc=4693.42,
            structure="有压管道",
            name="苟家湾",
            in_out="出",
            row_identity="flow1-row77",
        ),
    ]

    data = cad_tools._build_xxpipe_profile_data(
        nodes,
        {},
        station_prefix="赛支",
        export_policy={
            "allow_partial_export": True,
            "show_plain_pipe_name": True,
        },
    )

    assert len(data["material_segments"]) == 3
    assert data["material_segments"][1]["start_mc"] == pytest.approx(3971.87)
    assert data["material_segments"][1]["end_mc"] == pytest.approx(4366.58)
    assert data["material_segments"][1]["mid_mc"] == pytest.approx((3971.87 + 4366.58) / 2.0)


def test_draw_profile_on_msp_leaves_centerline_text_blank_when_relaxed_xxqu_axis_missing():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="有压管道", name="南干支线", in_out="进"),
        _make_node(ip_no=2, mc=50.0, structure="有压管道", name="南干支线"),
        _make_node(ip_no=3, mc=100.0, structure="有压管道", name="南干支线", in_out="出"),
    ]
    profile_data = cad_tools._build_xxpipe_profile_data(
        nodes,
        {},
        station_prefix="",
        export_policy={
            "allow_partial_export": True,
            "show_plain_pipe_name": True,
        },
    )
    msp = _DummyMSP()

    cad_tools._draw_profile_on_msp(
        msp,
        nodes,
        nodes,
        _scaled_settings(),
        station_prefix="",
        export_mode="xxpipe",
        xxpipe_profile_data=profile_data,
    )

    _settings, _enabled_ids, row_layout, _total_height, _line_height, _boundaries = cad_tools._build_xxpipe_profile_row_layout(
        _scaled_settings()
    )
    target_y = row_layout["centerline_elev"]["text_y"]
    row_texts = [
        rec["text"]
        for rec in msp.text_records
        if abs(rec["y"] - target_y) <= 1e-6 and rec["x"] >= 0
    ]

    assert row_texts == ["", "", ""]


def test_export_longitudinal_profile_dxf_shows_guidance_for_relaxed_xxqu(local_tmp_path, monkeypatch):
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="有压管道", name="南干支线", in_out="进"),
        _make_node(ip_no=2, mc=50.0, structure="有压管道", name="南干支线"),
        _make_node(ip_no=3, mc=100.0, structure="有压管道", name="南干支线", in_out="出"),
    ]
    out_file = local_tmp_path / "relaxed_xxqu_profile.dxf"
    infos = []
    errors = []
    docs = {}

    class _Dialog:
        def __init__(self, *_args, **_kwargs):
            self.result = {}

        def exec(self):
            return cad_tools.QDialog.Accepted

    class _FakeDoc:
        def __init__(self):
            self.saved_path = None
            self._msp = object()

        def modelspace(self):
            return self._msp

        def saveas(self, path):
            self.saved_path = path

    def _fake_new(_version):
        doc = _FakeDoc()
        docs["doc"] = doc
        return doc

    panel = SimpleNamespace(
        calculated_nodes=list(nodes),
        _text_export_settings={},
        channel_name_edit=SimpleNamespace(text=lambda: "测试渠"),
        channel_level_combo=SimpleNamespace(currentText=lambda: "支渠"),
    )
    panel.window = lambda: None
    panel._build_settings = lambda: _ProjSettings("")

    monkeypatch.setitem(sys.modules, "ezdxf", SimpleNamespace(new=_fake_new))
    monkeypatch.setattr(cad_tools, "MODELS_AVAILABLE", True)
    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "_resolve_xxpipe_export_source_nodes", lambda *_a, **_k: list(nodes))
    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _Dialog)
    monkeypatch.setattr(cad_tools, "_setup_profile_dxf_document", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_ensure_profile_layers", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", lambda *_a, **_k: (120.0, 80.0))
    monkeypatch.setattr(
        cad_tools,
        "_build_panel_xxpipe_profile_data",
        lambda *_a, **_k: {
            "profile_text_nodes": list(nodes),
            "centerline_records": [],
            "centerline_points": [],
            "ip_records": [],
            "building_segments": [],
            "material_segments": [],
            "warnings": {
                "allow_partial_export": True,
                "missing_axis_identities": ["1::南干支线"],
                "uncovered_stations": [],
            },
        },
    )
    monkeypatch.setattr(
        cad_tools.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_a, **_k: (str(out_file), "DXF")),
    )
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **_k: infos.append(args))
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **_k: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)

    cad_tools.export_longitudinal_profile_dxf(panel)

    assert docs["doc"].saved_path == str(out_file)
    assert not errors
    assert any("导入纵断面轴线DXF" in args[2] for args in infos)


def test_draw_tail_pressure_split_profile_on_msp_stacks_channel_and_xxpipe_tables(monkeypatch):
    calls = []

    def _fake_draw_profile_on_msp(
        msp,
        nodes,
        valid_nodes,
        settings,
        station_prefix,
        layer_prefix="",
        export_mode=None,
        xxpipe_profile_data=None,
        x_origin_mc=0.0,
    ):
        _ = (msp, valid_nodes, settings, station_prefix, layer_prefix, xxpipe_profile_data, x_origin_mc)
        calls.append(
            {
                "nodes": list(nodes),
                "export_mode": export_mode,
            }
        )
        if export_mode == "xxpipe":
            return 90.0, 70.0
        return 120.0, 110.0

    monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", _fake_draw_profile_on_msp)

    width, lower_depth = cad_tools._draw_tail_pressure_split_profile_on_msp(
        object(),
        _mixed_tail_nodes()[:3],
        _mixed_tail_nodes()[:3],
        _mixed_tail_nodes()[3:],
        _scaled_settings(),
        "",
        xxpipe_profile_data={"profile_text_nodes": _mixed_tail_nodes()[3:]},
    )

    assert len(calls) == 2
    assert calls[0]["export_mode"] is None
    assert calls[1]["export_mode"] == "xxpipe"
    assert width == pytest.approx(120.0)
    assert lower_depth == pytest.approx(150.0)


def test_draw_tail_pressure_split_profile_on_msp_rebases_lower_table_x_but_keeps_original_station_text(monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    channel_nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠1", bottom_elevation=410.0),
        _make_node(ip_no=2, mc=50.0, structure="明渠-矩形", name="明渠2", bottom_elevation=409.0),
        _make_node(ip_no=3, mc=100.0, structure="明渠-矩形", name="明渠3", bottom_elevation=408.0),
    ]
    tail_nodes = [
        _make_node(ip_no=4, mc=120.0, structure="有压管道", name="末端压力管", in_out="进", bottom_elevation=407.5),
        _make_node(ip_no=5, mc=160.0, structure="有压管道", name="末端压力管", bottom_elevation=406.7),
        _make_node(ip_no=6, mc=200.0, structure="有压管道", name="末端压力管", in_out="出", bottom_elevation=405.9),
    ]
    xxpipe_profile_data = cad_tools._build_xxpipe_profile_data(
        tail_nodes,
        {
            "1::末端压力管": [
                {"chainage": 120.0, "elevation": 100.0, "turn_type": "无"},
                {"chainage": 200.0, "elevation": 92.0, "turn_type": "无"},
            ]
        },
        station_prefix="",
    )
    msp = _DummyMSP()

    cad_tools._draw_tail_pressure_split_profile_on_msp(
        msp,
        channel_nodes,
        channel_nodes,
        tail_nodes,
        _scaled_settings(),
        "",
        xxpipe_profile_data=xxpipe_profile_data,
    )

    _settings, _enabled_ids, row_layout, _total_height, tail_line_height, _boundaries = cad_tools._build_xxpipe_profile_row_layout(
        _scaled_settings()
    )
    tail_offset_y = -(20.0 + float(tail_line_height))
    target_y = row_layout["station"]["text_y"] + tail_offset_y
    lower_station_texts = [
        (rec["text"], rec["x"])
        for rec in msp.text_records
        if abs(rec["y"] - target_y) <= 1e-6 and rec["x"] >= 0
    ]
    crossing_horizontal_lines = [
        rec
        for rec in msp.line_records
        if abs(rec["start"][1] - rec["end"][1]) <= 1e-6
        and rec["start"][1] < 0
        and min(rec["start"][0], rec["end"][0]) < 0
        and max(rec["start"][0], rec["end"][0]) > 0
    ]

    assert [text for text, _x in lower_station_texts] == ["0+120.00", "0+160.00", "0+200.00"]
    assert [x for _text, x in lower_station_texts] == pytest.approx([4.8, 19.0, 39.0])
    assert crossing_horizontal_lines == []


def test_draw_tail_pressure_split_profile_on_msp_keeps_single_upper_start_vline(monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    nodes = _mixed_tail_nodes_with_duplicate_channel_start()
    channel_nodes = nodes[:4]
    channel_valid_nodes = [node for node in channel_nodes if node.bottom_elevation or node.top_elevation or node.water_level]
    tail_nodes = nodes[4:]
    xxpipe_profile_data = cad_tools._build_xxpipe_profile_data(
        tail_nodes,
        {
            "1::末端压力管": [
                {"chainage": 150.0, "elevation": 100.0, "turn_type": "无"},
                {"chainage": 250.0, "elevation": 90.0, "turn_type": "无"},
            ]
        },
        station_prefix="",
    )
    msp = _DummyMSP()

    cad_tools._draw_tail_pressure_split_profile_on_msp(
        msp,
        channel_nodes,
        channel_valid_nodes,
        tail_nodes,
        _scaled_settings(),
        "",
        xxpipe_profile_data=xxpipe_profile_data,
    )

    _, row_layout, _, _line_height, _ = cad_tools._build_profile_row_layout(_scaled_settings())
    short_line_height = row_layout["slope"]["bottom"]

    assert _count_line(msp.line_records, (0.0, 0.0), (0.0, short_line_height)) == 1


def test_draw_tail_pressure_split_profile_on_msp_keeps_lower_centerline_text_when_route_profile_loaded(monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    channel_nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="明渠1", bottom_elevation=410.0),
        _make_node(ip_no=2, mc=50.0, structure="明渠-矩形", name="明渠2", bottom_elevation=409.0),
        _make_node(ip_no=3, mc=100.0, structure="明渠-矩形", name="明渠3", bottom_elevation=408.0),
    ]
    tail_nodes, xxpipe_profile_data = _build_route_level_tail_profile_data()
    msp = _DummyMSP()

    cad_tools._draw_tail_pressure_split_profile_on_msp(
        msp,
        channel_nodes,
        channel_nodes,
        tail_nodes,
        _scaled_settings(),
        "",
        xxpipe_profile_data=xxpipe_profile_data,
    )

    _settings, _enabled_ids, row_layout, _total_height, tail_line_height, _boundaries = cad_tools._build_xxpipe_profile_row_layout(
        _scaled_settings()
    )
    tail_offset_y = -(20.0 + float(tail_line_height))
    target_y = row_layout["centerline_elev"]["text_y"] + tail_offset_y
    lower_centerline_texts = [
        (rec["text"], rec["x"])
        for rec in msp.text_records
        if abs(rec["y"] - target_y) <= 1e-6 and rec["x"] >= 0
    ]

    assert [record["station_mc"] for record in xxpipe_profile_data["centerline_records"]] == pytest.approx(
        [120.0, 160.0, 200.0]
    )
    assert [record["elevation"] for record in xxpipe_profile_data["centerline_records"]] == pytest.approx(
        [100.0, 96.0, 92.0]
    )
    assert [text for text, _x in lower_centerline_texts] == ["100.00", "96.00", "92.00"]
    assert [x for _text, x in lower_centerline_texts] == pytest.approx([4.8, 19.0, 39.0])


def test_draw_profile_on_msp_does_not_promote_first_centerline_record_to_full_height_boundary(monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    tail_nodes, xxpipe_profile_data = _build_leading_gap_tail_profile_data()
    msp = _DummyMSP()

    cad_tools._draw_profile_on_msp(
        msp,
        tail_nodes,
        tail_nodes,
        _scaled_settings(),
        "",
        export_mode="xxpipe",
        xxpipe_profile_data=xxpipe_profile_data,
        x_origin_mc=1950.37,
    )

    scale_x = _scaled_settings()["scale_x"]
    _settings, _enabled_ids, row_layout, _total_height, _line_height, _boundaries = cad_tools._build_xxpipe_profile_row_layout(
        _scaled_settings()
    )
    expected_segment = [
        (
            row_layout["pipe_material"]["top"],
            row_layout["building_name"]["bottom"],
        )
    ]
    x_value = _scaled_m_to_mm(1981.787 - 1950.37, scale_x)

    assert _get_vertical_line_segments_at_x(msp.line_records, x_value) == pytest.approx(expected_segment)


def test_export_longitudinal_profile_dxf_uses_tail_pressure_split_helper_in_standard_mode(local_tmp_path, monkeypatch):
    nodes = _mixed_tail_nodes()
    out_file = local_tmp_path / "mixed_tail_profile.dxf"
    docs = {}
    captured = {}
    errors = []

    class _Dialog:
        def __init__(self, *_args, **_kwargs):
            self.result = {}

        def exec(self):
            return cad_tools.QDialog.Accepted

    class _FakeDoc:
        def __init__(self):
            self.saved_path = None
            self._msp = object()

        def modelspace(self):
            return self._msp

        def saveas(self, path):
            self.saved_path = path

    def _fake_new(_version):
        doc = _FakeDoc()
        docs["doc"] = doc
        return doc

    panel = SimpleNamespace(
        calculated_nodes=list(nodes),
        _text_export_settings={},
        channel_name_edit=SimpleNamespace(text=lambda: "测试渠"),
        channel_level_combo=SimpleNamespace(currentText=lambda: "支渠"),
    )
    panel.window = lambda: None
    panel._build_settings = lambda: _ProjSettings("")

    monkeypatch.setitem(sys.modules, "ezdxf", SimpleNamespace(new=_fake_new))
    monkeypatch.setattr(cad_tools, "MODELS_AVAILABLE", True)
    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _Dialog)
    monkeypatch.setattr(cad_tools, "_setup_profile_dxf_document", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_ensure_profile_layers", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cad_tools,
        "_resolve_tail_pressure_split_context",
        lambda *_a, **_k: {
            "channel_nodes": nodes[:3],
            "channel_valid_nodes": nodes[:3],
            "tail_nodes": nodes[3:],
            "xxpipe_profile_data": {"profile_text_nodes": nodes[3:]},
        },
        raising=False,
    )
    monkeypatch.setattr(
        cad_tools,
        "_draw_tail_pressure_split_profile_on_msp",
        lambda *_a, **_k: captured.update({"used_split_helper": True}) or (150.0, 210.0),
        raising=False,
    )
    monkeypatch.setattr(
        cad_tools,
        "_draw_profile_on_msp",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("不应回退到单表绘制")),
    )
    monkeypatch.setattr(
        cad_tools.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_a, **_k: (str(out_file), "DXF")),
    )
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **_k: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)

    cad_tools.export_longitudinal_profile_dxf(panel)

    assert docs["doc"].saved_path == str(out_file)
    assert not errors
    assert captured["used_split_helper"] is True


def test_export_longitudinal_profile_dxf_prefers_tail_split_for_xxqu_mixed_tail(local_tmp_path, monkeypatch):
    nodes = _mixed_tail_nodes()
    out_file = local_tmp_path / "mixed_tail_prefers_split.dxf"
    docs = {}
    captured = {"single_profile_called": False}

    class _Dialog:
        def __init__(self, *_args, **kwargs):
            captured["mode"] = kwargs.get("mode")
            self.result = {}

        def exec(self):
            return cad_tools.QDialog.Accepted

    class _FakeDoc:
        def __init__(self):
            self.saved_path = None
            self._msp = object()

        def modelspace(self):
            return self._msp

        def saveas(self, path):
            self.saved_path = path

    def _fake_new(_version):
        doc = _FakeDoc()
        docs["doc"] = doc
        return doc

    panel = SimpleNamespace(
        calculated_nodes=list(nodes),
        _text_export_settings={},
        channel_name_edit=SimpleNamespace(text=lambda: "赛金"),
        channel_level_combo=SimpleNamespace(currentText=lambda: "支渠"),
    )
    panel.window = lambda: None
    panel._build_settings = lambda: _ProjSettings("")

    monkeypatch.setitem(sys.modules, "ezdxf", SimpleNamespace(new=_fake_new))
    monkeypatch.setattr(cad_tools, "MODELS_AVAILABLE", True)
    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _Dialog)
    monkeypatch.setattr(cad_tools, "_setup_profile_dxf_document", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_ensure_profile_layers", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cad_tools.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_a, **_k: (str(out_file), "DXF")),
    )
    monkeypatch.setattr(
        cad_tools,
        "_resolve_tail_pressure_split_context",
        lambda *_a, **_k: {
            "channel_nodes": nodes[:3],
            "channel_valid_nodes": nodes[:3],
            "tail_nodes": nodes[3:],
            "xxpipe_profile_data": {"profile_text_nodes": nodes[3:]},
        },
        raising=False,
    )
    monkeypatch.setattr(
        cad_tools,
        "_draw_tail_pressure_split_profile_on_msp",
        lambda *_a, **_k: captured.update({"tail_split_called": True}) or (260.0, 180.0),
        raising=False,
    )

    def _unexpected_draw_profile(*_a, **_k):
        captured["single_profile_called"] = True
        return 240.0, 120.0

    monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", _unexpected_draw_profile)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)

    cad_tools.export_longitudinal_profile_dxf(panel)

    assert docs["doc"].saved_path == str(out_file)
    assert captured["mode"] == "standard"
    assert captured["tail_split_called"] is True
    assert captured["single_profile_called"] is False


def test_export_longitudinal_profile_dxf_keeps_xxpipe_branch_without_tail_split_detection(local_tmp_path, monkeypatch):
    nodes = _sample_nodes()
    out_file = local_tmp_path / "pure_xxpipe_profile.dxf"
    docs = {}
    captured = {"tail_split_called": False}
    errors = []

    class _Dialog:
        def __init__(self, *_args, **_kwargs):
            self.result = {}

        def exec(self):
            return cad_tools.QDialog.Accepted

    class _FakeDoc:
        def __init__(self):
            self.saved_path = None
            self._msp = object()

        def modelspace(self):
            return self._msp

        def saveas(self, path):
            self.saved_path = path

    def _fake_new(_version):
        doc = _FakeDoc()
        docs["doc"] = doc
        return doc

    panel = SimpleNamespace(
        calculated_nodes=list(nodes),
        _text_export_settings={},
        channel_name_edit=SimpleNamespace(text=lambda: "测试渠"),
        channel_level_combo=SimpleNamespace(currentText=lambda: "支管"),
    )
    panel.window = lambda: None
    panel._build_settings = lambda: _ProjSettings("")

    monkeypatch.setitem(sys.modules, "ezdxf", SimpleNamespace(new=_fake_new))
    monkeypatch.setattr(cad_tools, "MODELS_AVAILABLE", True)
    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "_resolve_xxpipe_export_source_nodes", lambda *_a, **_k: list(nodes))
    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _Dialog)
    monkeypatch.setattr(cad_tools, "_setup_profile_dxf_document", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_ensure_profile_layers", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cad_tools,
        "_resolve_tail_pressure_split_context",
        lambda *_a, **_k: captured.update({"tail_split_called": True}),
        raising=False,
    )
    monkeypatch.setattr(
        cad_tools,
        "_build_panel_xxpipe_profile_data",
        lambda *_a, **_k: captured.update({"xxpipe_nodes": list(_a[1])}) or {"profile_text_nodes": list(nodes)},
    )
    monkeypatch.setattr(
        cad_tools,
        "_draw_profile_on_msp",
        lambda *_a, **_k: captured.update({"draw_export_mode": _k.get("export_mode"), "draw_count": captured.get("draw_count", 0) + 1}) or (120.0, 80.0),
    )
    monkeypatch.setattr(
        cad_tools.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_a, **_k: (str(out_file), "DXF")),
    )
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **_k: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)

    cad_tools.export_longitudinal_profile_dxf(panel)

    assert docs["doc"].saved_path == str(out_file)
    assert not errors
    assert captured["tail_split_called"] is False
    assert [node.station_MC for node in captured["xxpipe_nodes"]] == pytest.approx([0.0, 50.0, 100.0])
    assert captured["draw_export_mode"] == "xxpipe"
    assert captured["draw_count"] == 1
