# -*- coding: utf-8 -*-
"""纵断面导出同桩号去重单元测试。"""

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
    spec = importlib.util.spec_from_file_location("cad_tools_longitudinal_dedup_test_mod", matches[0])
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

    def add_line(self, start, end, **_kwargs):
        self.line_records.append(
            {
                "start": (float(start[0]), float(start[1])),
                "end": (float(end[0]), float(end[1])),
            }
        )
        return None

    def add_lwpolyline(self, *_args, **_kwargs):
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
    is_transition=False,
):
    return _Node(
        station_MC=float(mc),
        bottom_elevation=float(bottom),
        top_elevation=float(top),
        water_level=float(water),
        structure_type=SimpleNamespace(value=structure),
        in_out=SimpleNamespace(value=in_out) if in_out else None,
        is_transition=bool(is_transition),
        name=name,
        ip_number=int(ip_no),
        slope_i=1 / 2000,
    )


def _sample_nodes():
    return [
        _make_node(ip_no=1, mc=0.0, bottom=410.0, top=412.0, water=411.0),
        _make_node(
            ip_no=15,
            mc=100.0,
            bottom=407.898,
            top=409.898,
            water=408.460,
            structure="隧洞-圆形",
            name="忘乡台",
            in_out="出",
        ),
        # 同桩号的隧洞非进/出节点，应被过滤（避免写入 0.000）
        _make_node(
            ip_no=16,
            mc=100.0,
            bottom=0.0,
            top=0.0,
            water=0.0,
            structure="隧洞-圆形",
            name="忘乡台",
            in_out="",
        ),
        _make_node(ip_no=20, mc=200.0, bottom=405.123, top=406.456, water=405.789),
        # 同桩号普通节点，靠“高程完整度优先”去重
        _make_node(ip_no=21, mc=200.0, bottom=0.0, top=0.0, water=0.0),
    ]


def _sample_multi_slope_nodes():
    n1 = _make_node(
        ip_no=1,
        mc=0.0,
        bottom=410.0,
        top=412.0,
        water=411.0,
        structure="明渠-矩形",
    )
    n1.slope_i = 1 / 2

    gate = _make_node(
        ip_no=2,
        mc=100.0,
        bottom=409.0,
        top=413.0,
        water=411.2,
        structure="节制闸",
        name="一号",
    )
    gate.slope_i = None

    n3 = _make_node(
        ip_no=3,
        mc=200.0,
        bottom=408.0,
        top=410.0,
        water=409.0,
        structure="明渠-矩形",
    )
    n3.slope_i = 1 / 5

    n4 = _make_node(
        ip_no=4,
        mc=300.0,
        bottom=407.0,
        top=409.0,
        water=408.0,
        structure="明渠-矩形",
    )
    n4.slope_i = 1 / 15

    return [n1, gate, n3, n4]


def _sample_current_as_endpoint_slope_nodes():
    n10 = _make_node(
        ip_no=10,
        mc=262.321,
        bottom=410.0,
        top=412.0,
        water=411.0,
        structure="隧洞-圆拱直墙型",
        name="叫化岩",
        in_out="出",
    )
    n10.slope_i = None

    n11 = _make_node(
        ip_no=11,
        mc=287.852,
        bottom=409.0,
        top=411.0,
        water=410.0,
        structure="明渠-矩形",
    )
    n11.slope_i = 1 / 2

    n12 = _make_node(
        ip_no=12,
        mc=318.787,
        bottom=408.0,
        top=410.0,
        water=409.0,
        structure="明渠-矩形",
    )
    n12.slope_i = 1 / 5

    n13 = _make_node(
        ip_no=13,
        mc=331.055,
        bottom=407.0,
        top=409.0,
        water=408.0,
        structure="明渠-矩形",
    )
    n13.slope_i = 1 / 15

    n14 = _make_node(
        ip_no=14,
        mc=348.836,
        bottom=406.0,
        top=408.0,
        water=407.0,
        structure="明渠-矩形",
    )
    n14.slope_i = 1 / 15

    n15 = _make_node(
        ip_no=15,
        mc=358.947,
        bottom=405.0,
        top=407.0,
        water=406.0,
        structure="明渠-矩形",
    )
    n15.slope_i = 1 / 2

    n16 = _make_node(
        ip_no=16,
        mc=419.606,
        bottom=404.0,
        top=406.0,
        water=405.0,
        structure="明渠-矩形",
    )
    n16.slope_i = 1 / 14

    n17 = _make_node(
        ip_no=17,
        mc=472.834,
        bottom=403.0,
        top=405.0,
        water=404.0,
        structure="明渠-矩形",
    )
    n17.slope_i = 1 / 14

    n18 = _make_node(
        ip_no=18,
        mc=561.362,
        bottom=402.0,
        top=404.0,
        water=403.0,
        structure="明渠-矩形",
    )
    n18.slope_i = 1 / 20

    n19 = _make_node(
        ip_no=19,
        mc=584.807,
        bottom=401.0,
        top=403.0,
        water=402.0,
        structure="明渠-矩形",
    )
    n19.slope_i = 1 / 20

    return [n10, n11, n12, n13, n14, n15, n16, n17, n18, n19]


def _sample_placeholder_slope_nodes():
    n1 = _make_node(
        ip_no=1,
        mc=100.0,
        bottom=410.0,
        top=412.0,
        water=411.0,
        structure="明渠-矩形",
    )
    n1.slope_i = None

    n2 = _make_node(
        ip_no=2,
        mc=150.0,
        bottom=409.0,
        top=411.0,
        water=410.0,
        structure="倒虹吸-圆形",
        name="一号",
        in_out="进",
    )
    n2.slope_i = None
    n2.is_inverted_siphon = True

    n3 = _make_node(
        ip_no=3,
        mc=210.0,
        bottom=408.0,
        top=410.0,
        water=409.0,
        structure="倒虹吸-圆形",
        name="一号",
        in_out="出",
    )
    n3.slope_i = None
    n3.is_inverted_siphon = True

    n4 = _make_node(
        ip_no=4,
        mc=280.0,
        bottom=407.0,
        top=409.0,
        water=408.0,
        structure="明渠-矩形",
    )
    n4.slope_i = 1 / 50

    return [n1, n2, n3, n4]


def _sample_rect_culvert_followed_by_special_placeholder_nodes():
    n1 = _make_node(
        ip_no=1,
        mc=0.0,
        bottom=410.0,
        top=412.0,
        water=411.0,
        structure="明渠-矩形",
    )
    n1.slope_i = None

    n2 = _make_node(
        ip_no=2,
        mc=50.0,
        bottom=409.0,
        top=411.0,
        water=410.0,
        structure="矩形暗涵",
    )
    n2.slope_i = 1 / 3000

    n3 = _make_node(
        ip_no=3,
        mc=60.0,
        bottom=408.0,
        top=410.0,
        water=409.0,
        structure="矩形暗涵",
    )
    n3.slope_i = 1 / 3000

    n4 = _make_node(
        ip_no=4,
        mc=61.0,
        bottom=407.0,
        top=409.0,
        water=408.0,
        structure="倒虹吸",
        name="陈家湾",
        in_out="进",
    )
    n4.slope_i = None

    n5 = _make_node(
        ip_no=5,
        mc=80.0,
        bottom=406.0,
        top=408.0,
        water=407.0,
        structure="倒虹吸",
        name="陈家湾",
        in_out="出",
    )
    n5.slope_i = None

    return [n1, n2, n3, n4, n5]


def _default_settings():
    return {
        "y_bottom": 1,
        "y_top": 31,
        "y_water": 16,
        "text_height": 3.5,
        "rotation": 90,
        "elev_decimals": 3,
        "station_decimals": 2,
        "y_name": 115,
        "y_slope": 105,
        "y_ip": 77,
        "y_station": 47,
        "y_line_height": 120,
        "scale_x": 1,
        "scale_y": 1,
    }

def _settings_with_enabled_rows(enabled_ids):
    settings = _default_settings()
    settings["profile_row_items"] = [
        {"id": rid, "enabled": rid in enabled_ids}
        for rid in cad_tools._PROFILE_ROW_DEFAULT_ORDER
    ]
    return settings


def _texts_at(records, x, y, tol=1e-6):
    return [
        rec["text"] for rec in records
        if abs(rec["x"] - x) <= tol and abs(rec["y"] - y) <= tol
    ]


def _row_records_at(records, y, tol=1e-6):
    return [rec for rec in records if abs(rec["y"] - y) <= tol]


def _assert_text_position_map(actual, expected):
    assert set(actual) == set(expected)
    for text, expected_xs in expected.items():
        assert sorted(actual[text]) == pytest.approx(sorted(expected_xs))


@pytest.fixture
def local_tmp_path():
    root = Path(__file__).resolve().parents[1]
    base_dir = root / ".pytest_tmp" / "water_profile_longitudinal_dedup_unit"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(dir=base_dir))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _parse_text_cmds(path):
    pat = re.compile(
        r"^-text(?:\s+j\s+mc)?\s+([-\d.eE]+),([-\d.eE]+)\s+[-\d.eE]+\s+[-\d.eE]+\s+(.+?)\s*$"
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


def _parse_pl_cmds(path):
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


def _scaled_m_to_mm(value_m, scale_denom):
    return float(value_m) * 1000.0 / float(scale_denom)


def test_draw_profile_on_msp_dedup_station_text(monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    nodes = _sample_nodes()
    valid_nodes = [n for n in nodes if n.bottom_elevation or n.top_elevation or n.water_level]
    msp = _DummyMSP()

    cad_tools._draw_profile_on_msp(
        msp,
        nodes,
        valid_nodes,
        _default_settings(),
        station_prefix="",
    )
    _, layout, _, line_height, _ = cad_tools._build_profile_row_layout(_default_settings())
    short_line_height = layout["slope"]["bottom"]
    scale_x = _default_settings()["scale_x"]
    x_100 = _scaled_m_to_mm(100.0, scale_x) - 1.0
    x_200 = _scaled_m_to_mm(200.0, scale_x) - 1.0

    # dxf 分支除首列外 x 会减 1；scale=1 现在表示严格 1:1（米 -> mm）
    assert _texts_at(msp.text_records, x_100, 1.0) == ["407.898"]
    assert _texts_at(msp.text_records, x_100, 16.0) == ["408.460"]
    assert _texts_at(msp.text_records, x_100, 31.0) == ["409.898"]
    assert _texts_at(msp.text_records, x_200, 1.0) == ["405.123"]
    assert _texts_at(msp.text_records, x_200, 16.0) == ["405.789"]
    assert _texts_at(msp.text_records, x_200, 31.0) == ["406.456"]

    assert "0.000" not in _texts_at(msp.text_records, x_100, 1.0)
    assert "0.000" not in _texts_at(msp.text_records, x_200, 1.0)
    assert len(_texts_at(msp.text_records, x_100, 47.0)) == 1
    assert len(_texts_at(msp.text_records, x_200, 47.0)) == 1
    assert any("忘乡台隧出" in txt for txt in _texts_at(msp.text_records, x_100, 77.0))
    assert _texts_at(msp.text_records, x_200, 77.0) == ["IP20"]
    assert _has_line(
        msp.line_records,
        (_scaled_m_to_mm(100.0, scale_x), 0.0),
        (_scaled_m_to_mm(100.0, scale_x), short_line_height),
    )
    assert _has_line(
        msp.line_records,
        (_scaled_m_to_mm(200.0, scale_x), 0.0),
        (_scaled_m_to_mm(200.0, scale_x), line_height),
    )


def test_export_longitudinal_txt_dedup_station_text(local_tmp_path, monkeypatch):
    nodes = _sample_nodes()
    valid_nodes = [n for n in nodes if n.bottom_elevation or n.top_elevation or n.water_level]
    out_file = local_tmp_path / "longitudinal_profile.txt"
    _, layout, _, line_height, _ = cad_tools._build_profile_row_layout(_default_settings())
    short_line_height = layout["slope"]["bottom"]
    scale_x = _default_settings()["scale_x"]

    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)

    cad_tools._export_longitudinal_txt_to_path(
        _Panel(""),
        nodes,
        valid_nodes,
        _default_settings(),
        str(out_file),
    )

    rows = _parse_text_cmds(out_file)
    pl_rows = _parse_pl_cmds(out_file)
    key = lambda x, y: [r["text"] for r in rows if abs(r["x"] - x) <= 1e-6 and abs(r["y"] - y) <= 1e-6]

    x_100 = _scaled_m_to_mm(100.0, scale_x)
    x_200 = _scaled_m_to_mm(200.0, scale_x)
    assert key(x_100, 1.0) == ["407.898"]
    assert key(x_100, 16.0) == ["408.460"]
    assert key(x_100, 31.0) == ["409.898"]
    assert key(x_200, 1.0) == ["405.123"]
    assert key(x_200, 16.0) == ["405.789"]
    assert key(x_200, 31.0) == ["406.456"]

    assert "0.000" not in key(x_100, 1.0)
    assert "0.000" not in key(x_200, 1.0)
    assert len(key(x_100, 47.0)) == 1
    assert len(key(x_200, 47.0)) == 1
    assert any("忘乡台隧出" in txt for txt in key(x_100, 77.0))
    assert key(x_200, 77.0) == ["IP20"]
    assert _has_line(pl_rows, (x_100, 0.0), (x_100, short_line_height))
    assert _has_line(pl_rows, (x_200, 0.0), (x_200, line_height))


def test_build_profile_slope_segments_returns_interval_records():
    nodes = _sample_current_as_endpoint_slope_nodes()

    segments = cad_tools._build_profile_slope_segments(nodes)

    assert segments == [
        {"text": "1/2", "start_mc": 262.321, "end_mc": 287.852},
        {"text": "1/5", "start_mc": 287.852, "end_mc": 318.787},
        {"text": "1/15", "start_mc": 318.787, "end_mc": 348.836},
        {"text": "1/2", "start_mc": 348.836, "end_mc": 358.947},
        {"text": "1/14", "start_mc": 358.947, "end_mc": 472.834},
        {"text": "1/20", "start_mc": 472.834, "end_mc": 584.807},
    ]


def test_profile_slope_segments_use_interval_centers_in_dxf_and_txt(local_tmp_path, monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    nodes = _sample_current_as_endpoint_slope_nodes()
    valid_nodes = nodes
    settings = _default_settings()
    _, layout, _, _, _ = cad_tools._build_profile_row_layout(settings)
    slope_y = layout["slope"]["text_y"]
    scale_x = settings["scale_x"]
    expected_positions = {
        "1/2": sorted([
            _scaled_m_to_mm((262.321 + 287.852) / 2.0, scale_x),
            _scaled_m_to_mm((348.836 + 358.947) / 2.0, scale_x),
        ]),
        "1/5": [_scaled_m_to_mm((287.852 + 318.787) / 2.0, scale_x)],
        "1/15": [_scaled_m_to_mm((318.787 + 348.836) / 2.0, scale_x)],
        "1/14": [_scaled_m_to_mm((358.947 + 472.834) / 2.0, scale_x)],
        "1/20": [_scaled_m_to_mm((472.834 + 584.807) / 2.0, scale_x)],
    }

    msp = _DummyMSP()
    cad_tools._draw_profile_on_msp(
        msp,
        nodes,
        valid_nodes,
        settings,
        station_prefix="",
    )
    dxf_rows = _row_records_at(msp.text_records, slope_y)
    dxf_positions = {}
    for rec in dxf_rows:
        if rec["text"] not in expected_positions:
            continue
        dxf_positions.setdefault(rec["text"], []).append(rec["x"])
    _assert_text_position_map(dxf_positions, expected_positions)

    out_file = local_tmp_path / "multi_slope_profile.txt"
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

    txt_rows = _parse_text_cmds(out_file)
    txt_positions = {}
    for rec in _row_records_at(txt_rows, slope_y):
        if rec["text"] not in expected_positions:
            continue
        txt_positions.setdefault(rec["text"], []).append(rec["x"])
    _assert_text_position_map(txt_positions, expected_positions)


def test_profile_slope_placeholder_segments_stay_isolated_from_open_channel(local_tmp_path, monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    nodes = _sample_placeholder_slope_nodes()
    settings = _default_settings()
    _, layout, _, _, _ = cad_tools._build_profile_row_layout(settings)
    slope_y = layout["slope"]["text_y"]
    scale_x = settings["scale_x"]

    segments = cad_tools._build_profile_slope_segments(nodes)
    assert segments == [
        {"text": "-", "start_mc": 100.0, "end_mc": 210.0},
        {"text": "1/50", "start_mc": 210.0, "end_mc": 280.0},
    ]

    expected_positions = {
        "-": [_scaled_m_to_mm((100.0 + 210.0) / 2.0, scale_x)],
        "1/50": [_scaled_m_to_mm((210.0 + 280.0) / 2.0, scale_x)],
    }

    msp = _DummyMSP()
    cad_tools._draw_profile_on_msp(msp, nodes, nodes, settings, station_prefix="")
    dxf_positions = {}
    for rec in _row_records_at(msp.text_records, slope_y):
        if rec["text"] not in expected_positions:
            continue
        dxf_positions.setdefault(rec["text"], []).append(rec["x"])
    _assert_text_position_map(dxf_positions, expected_positions)

    out_file = local_tmp_path / "placeholder_slope_profile.txt"
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)
    cad_tools._export_longitudinal_txt_to_path(_Panel(""), nodes, nodes, settings, str(out_file))

    txt_positions = {}
    for rec in _row_records_at(_parse_text_cmds(out_file), slope_y):
        if rec["text"] not in expected_positions:
            continue
        txt_positions.setdefault(rec["text"], []).append(rec["x"])
    _assert_text_position_map(txt_positions, expected_positions)


def test_profile_slope_segment_boundaries_draw_short_vlines_in_slope_row(local_tmp_path, monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    nodes = _sample_current_as_endpoint_slope_nodes()
    settings = _default_settings()
    _, layout, _, _, _ = cad_tools._build_profile_row_layout(settings)
    slope_bottom = layout["slope"]["bottom"]
    slope_top = layout["slope"]["top"]
    scale_x = settings["scale_x"]
    boundary_mcs = [287.852, 318.787, 348.836, 358.947, 472.834]
    merged_inner_mc = 331.055

    msp = _DummyMSP()
    cad_tools._draw_profile_on_msp(msp, nodes, nodes, settings, station_prefix="")
    for mc in boundary_mcs:
        x = _scaled_m_to_mm(mc, scale_x)
        assert _has_line(msp.line_records, (x, slope_bottom), (x, slope_top))
    merged_inner_x = _scaled_m_to_mm(merged_inner_mc, scale_x)
    assert not _has_line(msp.line_records, (merged_inner_x, slope_bottom), (merged_inner_x, slope_top))

    out_file = local_tmp_path / "slope_boundary_profile.txt"
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)
    cad_tools._export_longitudinal_txt_to_path(_Panel(""), nodes, nodes, settings, str(out_file))

    pl_rows = _parse_pl_cmds(out_file)
    for mc in boundary_mcs:
        x = _scaled_m_to_mm(mc, scale_x)
        assert _has_line(pl_rows, (x, slope_bottom), (x, slope_top))
    assert not _has_line(pl_rows, (merged_inner_x, slope_bottom), (merged_inner_x, slope_top))


def test_rect_culvert_boundary_does_not_draw_extra_slope_short_line_before_special_node(local_tmp_path, monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    nodes = _sample_rect_culvert_followed_by_special_placeholder_nodes()
    settings = _default_settings()
    _, layout, _, line_height, _ = cad_tools._build_profile_row_layout(settings)
    slope_bottom = layout["slope"]["bottom"]
    slope_top = layout["slope"]["top"]
    scale_x = settings["scale_x"]
    culvert_inner_x = _scaled_m_to_mm(60.0, scale_x)
    special_boundary_x = _scaled_m_to_mm(61.0, scale_x)

    msp = _DummyMSP()
    cad_tools._draw_profile_on_msp(msp, nodes, nodes, settings, station_prefix="")

    assert not _has_line(
        msp.line_records,
        (culvert_inner_x, slope_bottom),
        (culvert_inner_x, slope_top),
    )
    assert _has_line(
        msp.line_records,
        (special_boundary_x, 0.0),
        (special_boundary_x, line_height),
    )

    out_file = local_tmp_path / "rect_culvert_special_boundary_profile.txt"
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)
    cad_tools._export_longitudinal_txt_to_path(_Panel(""), nodes, nodes, settings, str(out_file))

    pl_rows = _parse_pl_cmds(out_file)
    assert not _has_line(
        pl_rows,
        (culvert_inner_x, slope_bottom),
        (culvert_inner_x, slope_top),
    )
    assert _has_line(
        pl_rows,
        (special_boundary_x, 0.0),
        (special_boundary_x, line_height),
    )


def test_profile_text_nodes_filter_transition_and_auto_inserted():
    real = _make_node(ip_no=10, mc=100.0, bottom=401.1, top=402.2, water=401.6)
    transition = _make_node(
        ip_no=11, mc=100.0, bottom=499.0, top=499.0, water=499.0, is_transition=True
    )
    auto_inserted = _make_node(ip_no=12, mc=100.0, bottom=398.0, top=398.0, water=398.0)
    auto_inserted.is_auto_inserted_channel = True
    another_real = _make_node(ip_no=20, mc=200.0, bottom=390.0, top=391.0, water=390.4)

    merged = cad_tools._build_profile_text_nodes([real, transition, auto_inserted, another_real])
    stations = [round(n.station_MC, 6) for n in merged]
    assert stations == [100.0, 200.0]
    assert merged[0].bottom_elevation == pytest.approx(401.1)
    assert merged[0].top_elevation == pytest.approx(402.2)
    assert merged[0].water_level == pytest.approx(401.6)


def test_profile_text_nodes_raise_on_same_station_conflicting_non_zero_values():
    n1 = _make_node(ip_no=1, mc=150.0, bottom=380.0, top=381.0, water=380.5)
    n2 = _make_node(ip_no=2, mc=150.0, bottom=381.2, top=381.0, water=380.5)
    with pytest.raises(ValueError, match="同桩号"):
        cad_tools._build_profile_text_nodes([n1, n2])


def test_single_point_segment_mid_resolves_to_cell_center():
    assert cad_tools._resolve_segment_mid_mc(0.0, 0.0, [0.0, 100.0]) == pytest.approx(50.0)
    assert cad_tools._resolve_segment_mid_mc(100.0, 100.0, [0.0, 100.0]) == pytest.approx(50.0)


def test_bd_be_bf_bj_bk_bl_offsets_match_station_rows_in_dxf_and_txt(local_tmp_path, monkeypatch):
    ezdxf_stub = SimpleNamespace(
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        )
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)

    n1 = _make_node(ip_no=11, mc=100.0, bottom=410.0, top=411.0, water=410.5)
    n2 = _make_node(ip_no=12, mc=200.0, bottom=409.0, top=410.0, water=409.5)
    for node, bc, ec in ((n1, 95.0, 105.0), (n2, 195.0, 205.0)):
        node.station_BC = bc
        node.station_EC = ec
        node.turn_angle = 8.0
    nodes = [n1, n2]
    valid_nodes = nodes

    enabled = {
        "station",
        "top_elev",
        "water_elev",
        "bottom_elev",
        "bd_ip_before",
        "bf_ip_after",
        "bj_station_before",
        "bl_station_after",
    }
    settings = _settings_with_enabled_rows(enabled)
    _, layout, _, _, _ = cad_tools._build_profile_row_layout(settings)
    ip_records = cad_tools._build_ip_related_row_records(
        nodes,
        "",
        station_decimals=settings["station_decimals"],
    )
    first_offset = settings["text_height"] + 1.3
    scale_x = settings["scale_x"]

    msp = _DummyMSP()
    cad_tools._draw_profile_on_msp(msp, nodes, valid_nodes, settings, station_prefix="")

    for rid in ("bd_ip_before", "bf_ip_after", "bj_station_before", "bl_station_after"):
        y = layout[rid]["text_y"]
        row_records = [r for r in msp.text_records if abs(r["y"] - y) <= 1e-6]
        assert len(row_records) >= 2
        for idx, rec in enumerate(ip_records[rid]):
            scaled_x = _scaled_m_to_mm(rec["x"], scale_x)
            expected_x = scaled_x + first_offset if idx == 0 else scaled_x - 1
            matched = [
                item for item in row_records
                if abs(item["x"] - expected_x) <= 1e-6 and item["text"] == rec["text"]
            ]
            assert matched, f"DXF row {rid} at idx={idx} does not match offset rule"

    out_file = local_tmp_path / "rows_offsets.txt"
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)
    cad_tools._export_longitudinal_txt_to_path(_Panel(""), nodes, valid_nodes, settings, str(out_file))
    rows = _parse_text_cmds(out_file)

    for rid in ("bd_ip_before", "bf_ip_after", "bj_station_before", "bl_station_after"):
        y = layout[rid]["text_y"]
        row_records = [r for r in rows if abs(r["y"] - y) <= 1e-6]
        assert len(row_records) >= 2
        for idx, rec in enumerate(ip_records[rid]):
            scaled_x = _scaled_m_to_mm(rec["x"], scale_x)
            expected_x = scaled_x + first_offset if idx == 0 else scaled_x
            matched = [
                item for item in row_records
                if abs(item["x"] - expected_x) <= 1e-6 and item["text"] == rec["text"]
            ]
            assert matched, f"TXT row {rid} at idx={idx} does not match offset rule"
