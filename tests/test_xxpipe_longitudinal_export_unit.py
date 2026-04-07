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
    assert "穿路段定向钻" in texts
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
    assert "穿路段定向钻" in content
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
    assert [segment["text"] for segment in data["building_segments"]] == ["穿山段隧洞-圆形"]
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
