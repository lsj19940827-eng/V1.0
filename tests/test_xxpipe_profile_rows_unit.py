# -*- coding: utf-8 -*-
"""xx管 纵断面固定模板与文案规则测试。"""

from pathlib import Path
import importlib.util

import pytest


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_xxpipe_profile_rows_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


def test_xxpipe_profile_rows_are_fixed_five_lines():
    rows = cad_tools._get_xxpipe_profile_row_defs()

    assert [row["id"] for row in rows] == [
        "building_name",
        "ip_name",
        "station",
        "centerline_elev",
        "pipe_material",
    ]
    assert rows[0]["header_lines"] == ["建筑物名称"]
    assert rows[2]["header_lines"] == ["里程桩号", "（千米+米）"]
    assert rows[3]["header_lines"] == ["管中心线高程（米）"]
    assert rows[4]["header_lines"] == ["管材（管径）"]


def test_xxpipe_rule_helpers_cover_channel_level_and_structure_scope():
    assert cad_tools._is_xxpipe_channel_level("支管")
    assert cad_tools._is_xxpipe_channel_level("总干管")
    assert not cad_tools._is_xxpipe_channel_level("支渠")

    assert cad_tools._is_xxpipe_allowed_structure("有压管道")
    assert cad_tools._is_xxpipe_allowed_structure("隧洞-圆形")
    assert cad_tools._is_xxpipe_allowed_structure("定向钻")
    assert cad_tools._is_xxpipe_allowed_structure("顶管")
    assert not cad_tools._is_xxpipe_allowed_structure("明渠-矩形")


def test_xxpipe_building_name_keeps_user_name_for_plain_pipe():
    assert cad_tools._get_xxpipe_building_display_name("有压管道", "普通管") == "普通管"
    assert cad_tools._get_xxpipe_building_display_name("有压管道", "") == ""
    assert cad_tools._get_xxpipe_building_display_name("定向钻", "穿路段") == "穿路段"
    assert cad_tools._get_xxpipe_building_display_name("顶管", "") == "顶管"
    assert cad_tools._get_xxpipe_building_display_name("隧洞-圆形", "1#洞段") == "1#洞段"


def test_xxpipe_pipe_material_text_uses_material_and_dn_only():
    assert cad_tools._format_xxpipe_pipe_material_text(
        {"pipe_material": "球墨铸铁管", "DN_mm": 1200}
    ) == "球墨铸铁管 DN1200"


def test_xxpipe_profile_row_layout_ignores_legacy_y_line_height():
    settings = {
        "text_height": 3.5,
        "rotation": 90,
        "elev_decimals": 3,
        "y_line_height": 180,
        "scale_x": 2000,
        "scale_y": 1000,
    }

    _settings, enabled_ids, row_layout, total_height, line_height, boundaries = cad_tools._build_xxpipe_profile_row_layout(settings)

    assert enabled_ids == [
        "building_name",
        "ip_name",
        "station",
        "centerline_elev",
        "pipe_material",
    ]
    assert total_height == pytest.approx(130.0)
    assert line_height == pytest.approx(130.0)
    assert boundaries == pytest.approx([0.0, 20.0, 40.0, 70.0, 110.0, 130.0])
    assert row_layout["building_name"]["top"] == pytest.approx(130.0)
    assert row_layout["pipe_material"]["bottom"] == pytest.approx(0.0)
