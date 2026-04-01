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
):
    return _Node(
        station_MC=float(mc),
        station_BC=float(mc),
        station_EC=float(mc),
        bottom_elevation=0.0,
        top_elevation=0.0,
        water_level=0.0,
        structure_type=SimpleNamespace(value=structure),
        in_out=SimpleNamespace(value=in_out) if in_out else None,
        is_transition=False,
        is_auto_inserted_channel=False,
        is_inverted_siphon=False,
        is_pressure_pipe=("有压管道" in structure),
        name=name,
        flow_section=flow_section,
        ip_number=int(ip_no),
        turn_angle=0.0,
        section_params={"pipe_material": "球墨铸铁管", "D": 1.2},
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
    assert "管材（管径/米）" in texts
    assert "穿路段定向钻" in texts
    assert "球墨铸铁管 DN1200" in texts
    assert "95.000" in texts


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

    assert _parse_polyline_vertex_cmds(out_file) == pytest.approx(
        [
            (0.0, 100.0),
            (25.0, 95.0),
            (50.0, 90.0),
        ]
    )


def test_build_xxpipe_profile_data_rejects_tunnel_structures():
    nodes = [
        _make_node(ip_no=1, mc=0.0, structure="隧洞-圆形", in_out="进"),
        _make_node(ip_no=2, mc=50.0, structure="隧洞-圆形"),
        _make_node(ip_no=3, mc=100.0, structure="隧洞-圆形", in_out="出"),
    ]

    with pytest.raises(ValueError, match="仅允许有压管道/定向钻/顶管"):
        cad_tools._build_xxpipe_profile_data(
            nodes,
            {
                "1::穿路段": [
                    {"chainage": 0.0, "elevation": 100.0, "turn_type": "无"},
                    {"chainage": 100.0, "elevation": 90.0, "turn_type": "无"},
                ]
            },
            station_prefix="",
        )


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
