# -*- coding: utf-8 -*-
"""纵断面行配置规则单元测试。"""

from pathlib import Path
import importlib.util
from types import SimpleNamespace


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


def test_station_before_after_row_heights_are_30():
    row_defs = cad_tools._PROFILE_ROW_DEF_MAP

    assert row_defs["bj_station_before"]["height"] == 30
    assert row_defs["bl_station_after"]["height"] == 30


def test_ip_related_records_suffix_and_duplicate_offset_rules():
    nodes = [
        _make_node(ip_no=1, mc=20, bc=10, ec=30, angle=12),
        _make_node(ip_no=2, mc=20, bc=10, ec=30, angle=15),  # 与上一行同BC/MC/EC，触发+6
        _make_node(
            ip_no=8, mc=420.5, bc=420.5, ec=420.5, angle=0,
            structure="隧洞-马蹄形", name="土地垭", in_out="进",
        ),
        _make_node(ip_no=3, mc=55, bc=50, ec=60, angle=0),  # 普通IP且F=0，无弯前/弯后
    ]
    rec = cad_tools._build_ip_related_row_records(nodes, station_prefix="")

    # 普通IP有转角：应有弯前/弯后
    assert rec["bd_ip_before"][0]["text"].endswith("弯前")
    assert rec["bf_ip_after"][0]["text"].endswith("弯后")

    # 第二条同桩号触发 +6 规则
    assert rec["bd_ip_before"][1]["x"] == rec["bd_ip_before"][0]["x"] + 6
    assert rec["be_ip_text"][1]["x"] == rec["be_ip_text"][0]["x"] + 6
    assert rec["bf_ip_after"][1]["x"] == rec["bf_ip_after"][0]["x"] + 6

    # 特殊建筑：结构全称+进出，且不加弯前/弯后
    assert rec["be_ip_text"][2]["text"] == "IP8 土地垭隧洞进"
    assert rec["bd_ip_before"][2]["text"] == "IP8 土地垭隧洞进"
    assert rec["bf_ip_after"][2]["text"] == "IP8 土地垭隧洞进"

    # 普通IP且F=0：不加弯前/弯后
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
    assert "IP21 甲倒虹吸进" in message
    assert "IP22 乙有压管道出" in message
