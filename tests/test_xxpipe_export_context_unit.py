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
    )


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
    assert [segment["text"] for segment in data["building_segments"]] == ["穿路段定向钻"]
    assert [segment["text"] for segment in data["material_segments"]] == ["球墨铸铁管 DN1200"]


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
