# -*- coding: utf-8 -*-
"""真实 xx管 样例回归测试。"""

from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

import pytest


def _load_cad_tools():
    """加载 cad_tools 模块。"""
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    spec = importlib.util.spec_from_file_location(
        "cad_tools_xxpipe_real_sample_test_mod",
        root / "app_渠系计算前端" / "water_profile" / "cad_tools.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_dxf_parser():
    """加载纵断面 DXF 解析器。"""
    root = Path(__file__).resolve().parents[1]
    parser_root = root / "倒虹吸水力计算系统"
    parser_root_str = str(parser_root)
    if parser_root_str not in sys.path:
        sys.path.insert(0, parser_root_str)
    spec = importlib.util.spec_from_file_location(
        "dxf_parser_xxpipe_real_sample_test_mod",
        parser_root / "dxf_parser.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DxfParser


cad_tools = _load_cad_tools()
DxfParser = _load_dxf_parser()


class _Node(SimpleNamespace):
    """测试用纵断面节点。"""

    def get_structure_type_str(self):
        """返回结构类型文本。"""
        struct = getattr(self, "structure_type", None)
        if struct is None:
            return ""
        if hasattr(struct, "value"):
            return struct.value
        return str(struct)


class _DummyMSP:
    """只记录折线输出的轻量模型空间。"""

    def __init__(self):
        self.polyline_records = []
        self.line_records = []
        self.text_records = []

    def add_line(self, start, end, dxfattribs=None):
        """记录线段。"""
        self.line_records.append(
            {
                "start": tuple(float(value) for value in start),
                "end": tuple(float(value) for value in end),
                "dxfattribs": dict(dxfattribs or {}),
            }
        )
        return None

    def add_lwpolyline(self, points, dxfattribs=None):
        """记录轻量多段线。"""
        self.polyline_records.append(
            {
                "points": [tuple(float(value) for value in point) for point in points],
                "dxfattribs": dict(dxfattribs or {}),
            }
        )
        return None

    def add_text(self, text, dxfattribs=None):
        """记录文字。"""

        class _TextEntity:
            def __init__(self, outer, raw_text, raw_dxfattribs):
                self._outer = outer
                self._text = raw_text
                self._dxfattribs = dict(raw_dxfattribs or {})

            def set_placement(self, point, align=None):
                self._outer.text_records.append(
                    {
                        "text": self._text,
                        "point": tuple(float(value) for value in point),
                        "align": align,
                        "dxfattribs": dict(self._dxfattribs),
                    }
                )
                return self

        return _TextEntity(self, text, dxfattribs)


def _make_node(ip_no, mc, row_identity, in_out=""):
    """构造最小 xx管 节点。"""
    return _Node(
        station_MC=float(mc),
        station_BC=float(mc),
        station_EC=float(mc),
        bottom_elevation=0.0,
        top_elevation=0.0,
        water_level=0.0,
        structure_type=SimpleNamespace(value="有压管道"),
        in_out=SimpleNamespace(value=in_out) if in_out else None,
        is_transition=False,
        is_auto_inserted_channel=False,
        is_inverted_siphon=False,
        is_pressure_pipe=True,
        name="九龙右支管",
        flow_section="1",
        ip_number=int(ip_no),
        turn_angle=0.0,
        section_params={"pipe_material": "球墨铸铁管", "D": 1.0},
        pressure_pipe_row_identity=row_identity,
    )


def test_real_jiulong_raw_profile_polyline_is_drawn_as_imported_source_line():
    """真实九龙右支管样例应直接按导入原线出图，而不是回退成采样折线。"""
    root = Path(__file__).resolve().parents[1]
    source_path = root / "data" / "九龙右支管纵剖面图.dxf"
    if not source_path.exists():
        pytest.skip("缺少真实样例 DXF")

    raw_profile_without_offset, error = DxfParser.get_longitudinal_profile_raw_polyline(
        str(source_path),
        chainage_offset=0.0,
    )
    assert error == ""
    assert raw_profile_without_offset

    chainage_offset = -float(raw_profile_without_offset["vertices"][0][0])
    raw_profile_polyline, error = DxfParser.get_longitudinal_profile_raw_polyline(
        str(source_path),
        chainage_offset=chainage_offset,
    )
    assert error == ""
    vertices = list(raw_profile_polyline["vertices"])
    assert len(vertices) > 200

    start_vertex = vertices[0]
    middle_vertex = vertices[len(vertices) // 2]
    end_vertex = vertices[-1]

    nodes = [
        _make_node(1, start_vertex[0], "flow1-row1", "进"),
        _make_node(2, middle_vertex[0], "flow1-row2"),
        _make_node(3, end_vertex[0], "flow1-row3", "出"),
    ]
    engineering_nodes = [
        {
            "chainage": float(start_vertex[0]),
            "elevation": float(start_vertex[1]),
            "turn_type": "NONE",
            "turn_angle": 0.0,
        },
        {
            "chainage": float(middle_vertex[0]),
            "elevation": float(middle_vertex[1]),
            "turn_type": "FOLD",
            "turn_angle": 3.0,
        },
        {
            "chainage": float(end_vertex[0]),
            "elevation": float(end_vertex[1]),
            "turn_type": "NONE",
            "turn_angle": 0.0,
        },
    ]
    long_map = {
        key: list(engineering_nodes)
        for key in ["flow1-row1", "flow1-row2", "flow1-row3"]
    }
    warning_context = {
        key: {
            "identity": key,
            "route_key": "jiulong-route",
            "route_display_name": "九龙右支管",
        }
        for key in ["flow1-row1", "flow1-row2", "flow1-row3"]
    }
    manager_map = {
        key: {
            "segment_geometry_source": "route_raw_profile_polyline",
        }
        for key in ["flow1-row1", "flow1-row2", "flow1-row3"]
    }

    profile_data = cad_tools._build_xxpipe_profile_data(
        nodes,
        long_map,
        station_prefix="",
        raw_profile_polylines_by_route={"jiulong-route": raw_profile_polyline},
        manager_config_by_identity=manager_map,
        warning_context_by_identity=warning_context,
    )

    assert len(profile_data["centerline_records"]) == 3
    assert len(profile_data["profile_breakpoint_records"]) == 3
    assert len(profile_data["centerline_draw_segments"]) == 1
    draw_segment = profile_data["centerline_draw_segments"][0]
    assert draw_segment["source_kind"] == "route_raw_profile_polyline"
    assert len(draw_segment["points"]) == len(vertices)
    assert draw_segment["points"][0] == pytest.approx(vertices[0])
    assert draw_segment["points"][-1] == pytest.approx(vertices[-1])

    settings = {
        "text_height": 3.5,
        "rotation": 90,
        "elev_decimals": 3,
        "xxpipe_centerline_elev_decimals": 2,
        "xxpipe_station_decimals": 2,
        "y_line_height": 120,
        "scale_x": 1,
        "scale_y": 1,
    }
    msp = _DummyMSP()
    cad_tools._draw_xxpipe_profile_on_msp(
        msp,
        nodes,
        settings,
        "",
        xxpipe_profile_data=profile_data,
    )

    centerline_polylines = [
        item
        for item in msp.polyline_records
        if item["dxfattribs"].get("layer") == "管中心线"
    ]
    assert len(centerline_polylines) == 1
    assert len(centerline_polylines[0]["points"]) == len(vertices)
    assert len(centerline_polylines[0]["points"]) != len(profile_data["centerline_records"])
