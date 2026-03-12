# -*- coding: utf-8 -*-
"""纵断面导出同桩号去重单元测试。"""

from pathlib import Path
import importlib.util
import re
import sys
from types import SimpleNamespace
import pytest


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
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

    def add_line(self, *_args, **_kwargs):
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


def _default_settings():
    return {
        "y_bottom": 1,
        "y_top": 31,
        "y_water": 16,
        "text_height": 3.5,
        "rotation": 90,
        "elev_decimals": 3,
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

    # dxf 分支除首列外 x 会减 1，因此 station=100/200 的文本 x 分别是 99/199
    assert _texts_at(msp.text_records, 99.0, 1.0) == ["407.898"]
    assert _texts_at(msp.text_records, 99.0, 16.0) == ["408.460"]
    assert _texts_at(msp.text_records, 99.0, 31.0) == ["409.898"]
    assert _texts_at(msp.text_records, 199.0, 1.0) == ["405.123"]
    assert _texts_at(msp.text_records, 199.0, 16.0) == ["405.789"]
    assert _texts_at(msp.text_records, 199.0, 31.0) == ["406.456"]

    assert "0.000" not in _texts_at(msp.text_records, 99.0, 1.0)
    assert "0.000" not in _texts_at(msp.text_records, 199.0, 1.0)
    assert len(_texts_at(msp.text_records, 99.0, 47.0)) == 1
    assert len(_texts_at(msp.text_records, 199.0, 47.0)) == 1
    assert any("IP15" in txt for txt in _texts_at(msp.text_records, 99.0, 77.0))
    assert _texts_at(msp.text_records, 199.0, 77.0) == ["IP20"]


def test_export_longitudinal_txt_dedup_station_text(tmp_path, monkeypatch):
    nodes = _sample_nodes()
    valid_nodes = [n for n in nodes if n.bottom_elevation or n.top_elevation or n.water_level]
    out_file = tmp_path / "longitudinal_profile.txt"

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
    key = lambda x, y: [r["text"] for r in rows if abs(r["x"] - x) <= 1e-6 and abs(r["y"] - y) <= 1e-6]

    assert key(100.0, 1.0) == ["407.898"]
    assert key(100.0, 16.0) == ["408.460"]
    assert key(100.0, 31.0) == ["409.898"]
    assert key(200.0, 1.0) == ["405.123"]
    assert key(200.0, 16.0) == ["405.789"]
    assert key(200.0, 31.0) == ["406.456"]

    assert "0.000" not in key(100.0, 1.0)
    assert "0.000" not in key(200.0, 1.0)
    assert len(key(100.0, 47.0)) == 1
    assert len(key(200.0, 47.0)) == 1
    assert any("IP15" in txt for txt in key(100.0, 77.0))
    assert key(200.0, 77.0) == ["IP20"]


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


def test_bd_be_bf_bj_bk_bl_offsets_match_station_rows_in_dxf_and_txt(tmp_path, monkeypatch):
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
    ip_records = cad_tools._build_ip_related_row_records(nodes, "")
    first_offset = settings["text_height"] + 1.3

    msp = _DummyMSP()
    cad_tools._draw_profile_on_msp(msp, nodes, valid_nodes, settings, station_prefix="")

    for rid in ("bd_ip_before", "bf_ip_after", "bj_station_before", "bl_station_after"):
        y = layout[rid]["text_y"]
        row_records = [r for r in msp.text_records if abs(r["y"] - y) <= 1e-6]
        assert len(row_records) >= 2
        for idx, rec in enumerate(ip_records[rid]):
            expected_x = rec["x"] + first_offset if idx == 0 else rec["x"] - 1
            matched = [
                item for item in row_records
                if abs(item["x"] - expected_x) <= 1e-6 and item["text"] == rec["text"]
            ]
            assert matched, f"DXF row {rid} at idx={idx} does not match offset rule"

    out_file = tmp_path / "rows_offsets.txt"
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
            expected_x = rec["x"] + first_offset if idx == 0 else rec["x"]
            matched = [
                item for item in row_records
                if abs(item["x"] - expected_x) <= 1e-6 and item["text"] == rec["text"]
            ]
            assert matched, f"TXT row {rid} at idx={idx} does not match offset rule"
