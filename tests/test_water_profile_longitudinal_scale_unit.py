# -*- coding: utf-8 -*-
"""纵断面比例换算回归测试。"""

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
        "cad_tools_longitudinal_scale_test_mod",
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
    bottom,
    top,
    water,
    structure="明渠-矩形",
    name="",
    in_out="",
):
    return _Node(
        station_MC=float(mc),
        bottom_elevation=float(bottom),
        top_elevation=float(top),
        water_level=float(water),
        structure_type=SimpleNamespace(value=structure),
        in_out=SimpleNamespace(value=in_out) if in_out else None,
        is_transition=False,
        name=name,
        ip_number=int(ip_no),
        slope_i=1 / 2000,
    )


def _sample_nodes():
    return [
        _make_node(ip_no=1, mc=0.0, bottom=410.0, top=412.0, water=411.0),
        _make_node(ip_no=15, mc=100.0, bottom=407.898, top=409.898, water=408.460),
        _make_node(ip_no=20, mc=200.0, bottom=405.123, top=406.456, water=405.789),
    ]


def _scaled_settings():
    return {
        "y_bottom": 1,
        "y_top": 31,
        "y_water": 16,
        "text_height": 3.5,
        "rotation": 90,
        "elev_decimals": 3,
        "xxpipe_centerline_elev_decimals": 2,
        "y_name": 115,
        "y_slope": 105,
        "y_ip": 77,
        "y_station": 47,
        "y_line_height": 120,
        "scale_x": 2000,
        "scale_y": 1000,
    }


def test_normalize_text_export_settings_defaults_to_profile_ratios():
    normalized = cad_tools._normalize_text_export_settings({})

    assert normalized["scale_x"] == 2000
    assert normalized["scale_y"] == 1000


def _texts_at(records, x, y, tol=1e-6):
    return [
        rec["text"] for rec in records
        if abs(rec["x"] - x) <= tol and abs(rec["y"] - y) <= tol
    ]


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[1]
    base_dir = root / ".pytest_tmp" / "water_profile_longitudinal_scale_unit"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(dir=base_dir))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


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


def _parse_text_cmds(path):
    pat = re.compile(
        r"^-text\s+([-\d.eE]+),([-\d.eE]+)\s+[-\d.eE]+\s+[-\d.eE]+\s+(.+?)\s*$"
    )
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        rows.append(
            {
                "x": float(m.group(1)),
                "y": float(m.group(2)),
                "text": m.group(3).strip(),
            }
        )
    return rows


def _parse_two_point_pl_cmds(path):
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


def _parse_polyline_vertex_cmds(path):
    pat = re.compile(r"^pl\s+([-\d.eE]+),([-\d.eE]+)\s*$")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        rows.append((float(m.group(1)), float(m.group(2))))
    return rows


def test_draw_profile_on_msp_uses_mm_per_ratio_scale(monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    settings = _scaled_settings()
    nodes = _sample_nodes()
    valid_nodes = nodes
    msp = _DummyMSP()

    width, _height = cad_tools._draw_profile_on_msp(
        msp,
        nodes,
        valid_nodes,
        settings,
        station_prefix="",
    )

    _, layout, _, line_height, _ = cad_tools._build_profile_row_layout(settings)
    short_line_height = layout["slope"]["bottom"]

    assert width == pytest.approx(140.0)
    assert _has_line(msp.line_records, (50.0, 0.0), (50.0, short_line_height))
    assert _has_line(msp.line_records, (100.0, 0.0), (100.0, line_height))

    bottom_polyline = next(
        rec for rec in msp.polyline_records if rec["layer"] == "渠底高程线"
    )
    assert bottom_polyline["points"][:3] == pytest.approx(
        [
            (0.0, 410.0),
            (50.0, 407.898),
            (100.0, 405.123),
        ]
    )

    assert _texts_at(msp.text_records, 49.0, 1.0) == ["407.898"]
    assert _texts_at(msp.text_records, 99.0, 1.0) == ["405.123"]


def test_export_longitudinal_txt_uses_same_mm_per_ratio_scale(local_tmp_path, monkeypatch):
    settings = _scaled_settings()
    nodes = _sample_nodes()
    valid_nodes = nodes
    out_file = local_tmp_path / "longitudinal_profile_scaled.txt"

    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)

    cad_tools._export_longitudinal_txt_to_path(
        _Panel(""),
        nodes,
        valid_nodes,
        settings,
        str(out_file),
    )

    _, layout, _, line_height, _ = cad_tools._build_profile_row_layout(settings)
    short_line_height = layout["slope"]["bottom"]
    text_rows = _parse_text_cmds(out_file)
    line_rows = _parse_two_point_pl_cmds(out_file)
    poly_vertices = _parse_polyline_vertex_cmds(out_file)

    key = lambda x, y: [
        rec["text"]
        for rec in text_rows
        if abs(rec["x"] - x) <= 1e-6 and abs(rec["y"] - y) <= 1e-6
    ]

    assert key(50.0, 1.0) == ["407.898"]
    assert key(100.0, 1.0) == ["405.123"]
    assert _has_line(line_rows, (50.0, 0.0), (50.0, short_line_height))
    assert _has_line(line_rows, (100.0, 0.0), (100.0, line_height))
    assert (50.0, 407.898) in poly_vertices
    assert (100.0, 405.123) in poly_vertices


def test_setup_profile_dxf_document_sets_mm_headers():
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new("R2010")

    cad_tools._setup_profile_dxf_document(doc)

    assert doc.header["$INSUNITS"] == 4
    assert doc.header["$MEASUREMENT"] == 1
