# -*- coding: utf-8 -*-
"""纵断面行配置规则单元测试。"""

from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

import pytest


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_profile_rows_test_mod", matches[0])
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

    def get_ip_str(self):
        """按主模型规则返回当前节点的显示 IP 文本。"""
        in_out = getattr(getattr(self, "in_out", None), "value", "")
        struct = self.get_structure_type_str()
        display_ip_no = getattr(self, "display_ip_number", None)
        if display_ip_no is None:
            display_ip_no = getattr(self, "ip_number", 0)
        if in_out in ("进", "出") and "暗涵" not in struct:
            struct_abbr = ""
            if "隧洞" in struct:
                struct_abbr = "隧"
            elif "倒虹吸" in struct:
                struct_abbr = "倒"
            elif "渡槽" in struct:
                struct_abbr = "渡"
            elif "定向钻" in struct:
                struct_abbr = "定向钻"
            elif "顶管" in struct:
                struct_abbr = "顶管"
            elif "有压管道" in struct:
                struct_abbr = "有压管道"
            return f"{getattr(self, 'name', '')}{struct_abbr}{in_out}"
        return f"IP{display_ip_no}"


def _make_node(
    *,
    ip_no,
    mc,
    bc=None,
    ec=None,
    angle=0.0,
    structure="明渠-矩形",
    name="",
    in_out="",
    is_transition=False,
):
    return _Node(
        ip_number=ip_no,
        display_ip_number=ip_no,
        station_MC=float(mc),
        station_BC=float(mc if bc is None else bc),
        station_EC=float(mc if ec is None else ec),
        turn_angle=float(angle),
        structure_type=SimpleNamespace(value=structure),
        name=name,
        in_out=SimpleNamespace(value=in_out) if in_out else None,
        is_transition=is_transition,
        bottom_elevation=430.0,
        top_elevation=432.0,
        water_level=431.2,
        slope_i=1 / 2000,
    )


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

    def add_line(self, start, end, dxfattribs=None):
        self.line_records.append(
            {
                "start": (float(start[0]), float(start[1])),
                "end": (float(end[0]), float(end[1])),
                "dxfattribs": dict(dxfattribs or {}),
            }
        )
        return None

    def add_lwpolyline(self, points, dxfattribs=None):
        self.polyline_records.append(
            {
                "points": [(float(x), float(y)) for x, y in points],
                "dxfattribs": dict(dxfattribs or {}),
            }
        )
        return None

    def add_text(self, text, dxfattribs=None):
        return _TextEntity(self, text, dxfattribs)


def _has_line(records, start, end, tol=1e-6):
    for rec in records:
        if (
            abs(rec["start"][0] - start[0]) <= tol
            and abs(rec["start"][1] - start[1]) <= tol
            and abs(rec["end"][0] - end[0]) <= tol
            and abs(rec["end"][1] - end[1]) <= tol
        ):
            return True
    return False


def _draw_settings():
    return {
        "text_height": 3.5,
        "rotation": 90,
        "elev_decimals": 3,
        "station_decimals": 2,
        "y_line_height": 120,
        "scale_x": 2000,
        "scale_y": 1000,
        "profile_row_items": cad_tools._default_profile_row_items(),
    }


def test_default_profile_row_items_hides_be_bk_and_keeps_tingzikou_enabled():
    rows = cad_tools._normalize_profile_row_items(None)
    assert len(rows) == 11

    enabled = [r["id"] for r in rows if r["enabled"]]
    assert enabled == [
        "building_name", "slope", "ip_name", "station",
        "top_elev", "water_elev", "bottom_elev",
    ]
    assert "be_ip_text" not in [r["id"] for r in rows]
    assert "bk_station" not in [r["id"] for r in rows]


def test_profile_row_layout_tingzikou_height_and_positions():
    settings = {
        "y_line_height": 120,
        "profile_row_items": cad_tools._default_profile_row_items(),
    }
    enabled_ids, layout, total_height, line_height, boundaries = cad_tools._build_profile_row_layout(settings)

    assert enabled_ids == [
        "building_name", "slope", "ip_name", "station",
        "top_elev", "water_elev", "bottom_elev",
    ]
    assert total_height == 135
    assert line_height == 135
    assert layout["building_name"]["top"] == 135
    assert layout["building_name"]["bottom"] == 125
    assert layout["station"]["height"] == 30
    assert 0 in boundaries and 135 in boundaries


def test_runtime_advanced_mapping_separates_legacy_writeback_and_enabled_runtime_rows():
    settings = {
        "y_line_height": 120,
        "profile_row_items": [
            {"id": "building_name", "enabled": True},
            {"id": "station", "enabled": True},
            {"id": "bottom_elev", "enabled": True},
            {"id": "slope", "enabled": False},
            {"id": "ip_name", "enabled": False},
            {"id": "top_elev", "enabled": False},
            {"id": "water_elev", "enabled": False},
            {"id": "bd_ip_before", "enabled": False},
            {"id": "bf_ip_after", "enabled": False},
            {"id": "bj_station_before", "enabled": False},
            {"id": "bl_station_after", "enabled": False},
        ],
    }

    runtime = cad_tools._compute_runtime_advanced_parameter_view(settings)

    assert runtime["legacy_writeback_values"]["y_name"] == 50.0
    assert runtime["legacy_writeback_values"]["y_station"] == 17.0
    assert runtime["legacy_writeback_values"]["y_bottom"] == 1.0
    assert runtime["legacy_writeback_values"]["y_top"] is None
    assert runtime["legacy_enabled_state"]["y_top"] is False
    assert runtime["line_height"] == 120.0
    assert [item["id"] for item in runtime["enabled_runtime_rows"]] == [
        "building_name",
        "station",
        "bottom_elev",
    ]
    assert runtime["enabled_runtime_rows"][0]["text_y"] == 50.0
    assert runtime["enabled_runtime_rows"][1]["source_label"] == "底+2 / 行高 30"
    assert runtime["row_details"] == runtime["enabled_runtime_rows"]


def test_enabled_runtime_rows_include_all_auxiliary_visible_rows():
    settings = {
        "y_line_height": 120,
        "profile_row_items": [
            {"id": "building_name", "enabled": True},
            {"id": "slope", "enabled": True},
            {"id": "ip_name", "enabled": True},
            {"id": "station", "enabled": True},
            {"id": "top_elev", "enabled": True},
            {"id": "water_elev", "enabled": True},
            {"id": "bottom_elev", "enabled": True},
            {"id": "bd_ip_before", "enabled": True},
            {"id": "bf_ip_after", "enabled": True},
            {"id": "bj_station_before", "enabled": True},
            {"id": "bl_station_after", "enabled": True},
        ],
    }

    runtime = cad_tools._compute_runtime_advanced_parameter_view(settings)
    enabled_runtime_rows = runtime["enabled_runtime_rows"]

    assert [item["id"] for item in enabled_runtime_rows] == [
        "building_name",
        "slope",
        "ip_name",
        "station",
        "top_elev",
        "water_elev",
        "bottom_elev",
        "bd_ip_before",
        "bf_ip_after",
        "bj_station_before",
        "bl_station_after",
    ]
    assert enabled_runtime_rows[7]["text_y"] == 102.0
    assert enabled_runtime_rows[8]["text_y"] == 62.0
    assert enabled_runtime_rows[9]["text_y"] == 32.0
    assert enabled_runtime_rows[10]["text_y"] == 2.0
    assert runtime["legacy_writeback_values"]["y_station"] == 187.0
    assert runtime["legacy_writeback_values"]["y_line_height"] == 275.0


def test_runtime_line_height_uses_max_of_content_height_and_compat_value():
    low_settings = {
        "y_line_height": 60,
        "profile_row_items": cad_tools._default_profile_row_items(),
    }
    high_settings = {
        "y_line_height": 220,
        "profile_row_items": cad_tools._default_profile_row_items(),
    }

    low_runtime = cad_tools._compute_runtime_advanced_parameter_view(low_settings)
    high_runtime = cad_tools._compute_runtime_advanced_parameter_view(high_settings)

    assert low_runtime["total_height"] == 135.0
    assert low_runtime["line_height"] == 135.0
    assert low_runtime["legacy_writeback_values"]["y_line_height"] == 135.0
    assert high_runtime["line_height"] == 220.0
    assert high_runtime["legacy_writeback_values"]["y_line_height"] == 220.0


def test_station_before_after_row_heights_are_30():
    row_defs = cad_tools._PROFILE_ROW_DEF_MAP

    assert row_defs["bj_station_before"]["height"] == 30
    assert row_defs["bl_station_after"]["height"] == 30


def test_ip_related_records_suffix_and_duplicate_offset_rules():
    nodes = [
        _make_node(ip_no=1, mc=20, bc=10, ec=30, angle=12),
        _make_node(ip_no=2, mc=20, bc=10, ec=30, angle=15),
        _make_node(
            ip_no=8, mc=420.5, bc=420.5, ec=420.5, angle=0,
            structure="隧洞-马蹄形", name="土地坝", in_out="进",
        ),
        _make_node(ip_no=3, mc=55, bc=50, ec=60, angle=0),
    ]
    rec = cad_tools._build_ip_related_row_records(nodes, station_prefix="")

    assert rec["bd_ip_before"][0]["text"].endswith("弯前")
    assert rec["bf_ip_after"][0]["text"].endswith("弯后")
    assert rec["bd_ip_before"][1]["x"] == rec["bd_ip_before"][0]["x"] + 6
    assert rec["be_ip_text"][1]["x"] == rec["be_ip_text"][0]["x"] + 6
    assert rec["bf_ip_after"][1]["x"] == rec["bf_ip_after"][0]["x"] + 6
    assert rec["be_ip_text"][2]["text"] == "土地坝隧进"
    assert rec["bd_ip_before"][2]["text"] == "土地坝隧进"
    assert rec["bf_ip_after"][2]["text"] == "土地坝隧进"
    assert rec["bd_ip_before"][3]["text"] == "IP3"
    assert rec["bf_ip_after"][3]["text"] == "IP3"


def test_special_angle_warning_contains_near_and_over_threshold():
    nodes = [
        _make_node(
            ip_no=21, mc=100, angle=0.005,
            structure="倒虹吸", name="甲", in_out="进",
        ),
        _make_node(
            ip_no=22, mc=200, angle=0.02,
            structure="有压管道", name="乙", in_out="出",
        ),
    ]
    message = cad_tools._build_special_angle_warning(nodes, tol_deg=0.01)
    assert "接近0" in message
    assert "超过阈值" in message
    assert "甲倒进" in message
    assert "乙有压管道出" in message


def test_profile_slope_segments_use_boundary_center_when_special_node_shifts_boundary():
    nodes = [
        _make_node(ip_no=1, mc=0, structure="明渠-矩形"),
        _make_node(ip_no=2, mc=50, structure="明渠-矩形"),
        _make_node(
            ip_no=3,
            mc=100,
            structure="隧洞-圆形",
            name="猴子山",
            in_out="进",
        ),
    ]
    nodes[0].slope_i = 1 / 3000
    nodes[1].slope_i = 1 / 3000
    nodes[2].slope_i = 1 / 1200

    segments = cad_tools._build_profile_slope_segments(nodes)

    assert segments[0]["start_mc"] == 0.0
    assert segments[0]["end_mc"] == 50.0
    assert segments[0]["mid_mc"] == 50.0


def test_profile_slope_segments_align_tunnel_segment_with_true_structure_cell():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形"),
        _make_node(ip_no=2, mc=80.0, structure="明渠-矩形"),
        _make_node(ip_no=3, mc=100.0, structure="隧洞-圆形", name="猴子山", in_out="进"),
        _make_node(ip_no=4, mc=220.0, structure="隧洞-圆形", name="猴子山", in_out="出"),
        _make_node(ip_no=5, mc=320.0, structure="明渠-矩形"),
    ]
    nodes[0].slope_i = 1 / 3000
    nodes[1].slope_i = 1 / 3000
    nodes[2].slope_i = 1 / 1200
    nodes[3].slope_i = 1 / 1200
    nodes[4].slope_i = 1 / 2000

    segments = cad_tools._build_profile_slope_segments(nodes)
    tunnel_segment = next(seg for seg in segments if seg["text"] == "1/1200")

    assert tunnel_segment["start_mc"] == pytest.approx(100.0)
    assert tunnel_segment["end_mc"] == pytest.approx(220.0)
    assert tunnel_segment["mid_mc"] == pytest.approx(160.0)


def test_profile_slope_segments_align_siphon_placeholder_with_true_structure_cell():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形"),
        _make_node(ip_no=2, mc=90.0, structure="明渠-矩形"),
        _make_node(ip_no=3, mc=110.0, structure="倒虹吸", name="桐油寨", in_out="进"),
        _make_node(ip_no=4, mc=260.0, structure="倒虹吸", name="桐油寨", in_out="出"),
        _make_node(ip_no=5, mc=360.0, structure="明渠-矩形"),
    ]
    nodes[0].slope_i = 1 / 3000
    nodes[1].slope_i = 1 / 3000
    nodes[2].slope_i = 1 / 2000
    nodes[3].slope_i = 1 / 2000
    nodes[4].slope_i = 1 / 1500

    segments = cad_tools._build_profile_slope_segments(nodes)
    siphon_segment = next(seg for seg in segments if seg["text"] == "-")

    assert siphon_segment["start_mc"] == pytest.approx(110.0)
    assert siphon_segment["end_mc"] == pytest.approx(260.0)
    assert siphon_segment["mid_mc"] == pytest.approx(185.0)


def test_get_building_display_name_falls_back_to_structure_for_unnamed_open_channel():
    node = _make_node(ip_no=5, mc=88, structure="明渠-圆形", name="")

    display = cad_tools._get_building_display_name(node)

    assert display == "明渠-圆形"


def test_draw_profile_on_msp_places_slope_text_at_true_boundary_center(monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="明渠-矩形", name="一支渠"),
        _make_node(ip_no=2, mc=80.0, structure="明渠-矩形", name="一支渠"),
        _make_node(ip_no=3, mc=100.0, structure="隧洞-圆拱直墙型", name="过山洞", in_out="进"),
        _make_node(ip_no=4, mc=220.0, structure="隧洞-圆拱直墙型", name="过山洞", in_out="出"),
        _make_node(ip_no=5, mc=320.0, structure="倒虹吸", name="桐油寨", in_out="进"),
        _make_node(ip_no=6, mc=470.0, structure="倒虹吸", name="桐油寨", in_out="出"),
        _make_node(ip_no=7, mc=560.0, structure="明渠-矩形", name="二支渠"),
    ]
    nodes[0].slope_i = 1 / 3000
    nodes[1].slope_i = 1 / 3000
    nodes[2].slope_i = 1 / 1200
    nodes[3].slope_i = 1 / 1200
    nodes[4].slope_i = 1 / 2000
    nodes[5].slope_i = 1 / 2000
    nodes[6].slope_i = 1 / 1500
    settings = _draw_settings()
    msp = _DummyMSP()

    cad_tools._draw_profile_on_msp(
        msp,
        nodes,
        nodes,
        settings,
        station_prefix="",
    )

    _enabled_ids, row_layout, _total_height, _line_height, _boundaries = cad_tools._build_profile_row_layout(settings)
    slope_y = row_layout["slope"]["text_y"]
    building_y = row_layout["building_name"]["text_y"]
    slope_records = [
        rec
        for rec in msp.text_records
        if abs(rec["y"] - slope_y) <= 1e-6
    ]
    building_records = [
        rec
        for rec in msp.text_records
        if abs(rec["y"] - building_y) <= 1e-6 and rec["x"] >= 0 and rec["text"] != "建筑物名称"
    ]
    slope_by_text = {rec["text"]: rec for rec in slope_records}
    building_by_text = {rec["text"]: rec for rec in building_records}

    assert slope_by_text["1/1200"]["x"] == pytest.approx(building_by_text["过山洞隧洞"]["x"])
    assert slope_by_text["-"]["x"] == pytest.approx(building_by_text["桐油寨倒虹吸"]["x"])


def test_standard_profile_middle_culvert_ip0_keeps_short_vline_and_aligned_slope(monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    nodes = [
        _make_node(ip_no=0, mc=0.0, structure="隧洞-圆形", name="大垭口", in_out="进"),
        _make_node(ip_no=1, mc=88.63878, structure="隧洞-圆形", name="大垭口", in_out="出"),
        _make_node(ip_no=0, mc=98.166893, structure="暗涵-矩形", in_out="进"),
        _make_node(ip_no=2, mc=108.251397, structure="隧洞-圆形", name="蓬莱", in_out="进"),
        _make_node(ip_no=3, mc=200.0, structure="隧洞-圆形", name="蓬莱", in_out="出"),
    ]
    for node in nodes:
        node.slope_i = 1 / 4000

    settings = _draw_settings()
    msp = _DummyMSP()

    cad_tools._draw_profile_on_msp(
        msp,
        nodes,
        nodes,
        settings,
        station_prefix="",
    )

    _enabled_ids, row_layout, _total_height, line_height, _boundaries = cad_tools._build_profile_row_layout(settings)
    slope_y = row_layout["slope"]["text_y"]
    building_y = row_layout["building_name"]["text_y"]
    short_line_height = row_layout["slope"]["bottom"]
    scale_x = settings["scale_x"]
    culvert_x = 98.166893 * 1000.0 / scale_x

    assert any(rec["text"] == "IP0" for rec in msp.text_records)
    assert _has_line(
        msp.line_records,
        (culvert_x, 0.0),
        (culvert_x, short_line_height),
    )
    assert not _has_line(
        msp.line_records,
        (culvert_x, 0.0),
        (culvert_x, line_height),
    )

    slope_xs = sorted(
        rec["x"]
        for rec in msp.text_records
        if abs(rec["y"] - slope_y) <= 1e-6 and rec["text"] == "1/4000"
    )
    building_xs = sorted(
        rec["x"]
        for rec in msp.text_records
        if abs(rec["y"] - building_y) <= 1e-6 and rec["text"] in {"大垭口隧洞", "暗涵-矩形", "蓬莱隧洞"}
    )

    assert slope_xs == pytest.approx(building_xs)
