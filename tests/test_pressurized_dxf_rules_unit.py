# -*- coding: utf-8 -*-
"""有压流导出规则（倒虹吸/有压管道）单元测试。"""

from pathlib import Path
import importlib.util
from types import SimpleNamespace


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


def _load_summary_module():
    root = Path(__file__).resolve().parents[1]
    matches = [p for p in root.glob("*/*.py") if p.name == "生成断面汇总表.py"]
    assert matches, "未找到 生成断面汇总表.py"
    spec = importlib.util.spec_from_file_location("summary_table_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


summary_mod = _load_summary_module()


def _node(
    *,
    structure_type,
    name="",
    d=0.0,
    h=0.0,
    is_siphon=False,
    is_transition=False,
    is_auto=False,
):
    return SimpleNamespace(
        is_transition=is_transition,
        is_auto_inserted_channel=is_auto,
        is_inverted_siphon=is_siphon,
        structure_type=SimpleNamespace(value=structure_type),
        name=name,
        section_params={"D": d} if d else {},
        structure_height=h,
    )


def test_parse_positive_dn():
    assert cad_tools._parse_positive_dn("1500") == 1500
    assert cad_tools._parse_positive_dn("1500.0") == 1500
    assert cad_tools._parse_positive_dn("1500.5") is None
    assert cad_tools._parse_positive_dn("-1") is None
    assert cad_tools._parse_positive_dn("abc") is None


def test_extract_named_pressurized_groups():
    nodes = [
        _node(structure_type="倒虹吸", name="虹吸A", d=1.6, is_siphon=True),
        _node(structure_type="倒虹吸", name="虹吸A", d=1.4, is_siphon=True),
        _node(structure_type="有压管道", name="管道1", d=2.0),
        _node(structure_type="有压管道", name="", h=1.8),
    ]
    siphon_groups = cad_tools._extract_named_pressurized_groups(nodes, "siphon")
    pressure_groups = cad_tools._extract_named_pressurized_groups(nodes, "pressure_pipe")

    assert siphon_groups == [("虹吸A", 1600.0)]
    assert pressure_groups == [("管道1", 2000.0), ("有压管道", 1800.0)]


def test_merge_pressurized_param_defaults():
    groups = [("管道1", 2000), ("管道2", 0)]
    cached = [("管道1", "钢管", 1800), ("旧管道", "PCCP管", 1600)]

    merged = cad_tools._merge_pressurized_param_defaults(groups, cached)

    assert merged[0] == ("管道1", "钢管", 1800)
    assert merged[1] == ("管道2", "球墨铸铁管", 1500)


def test_build_pressurized_segments_keeps_distinct_rows_for_distinct_params():
    qs = [2.0, 1.0]
    overrides = {1: {"n": 0.012}, 2: {"n": 0.013}}
    params = [("管道A", "钢管", 1800), ("管道B", "球墨铸铁管", 1600)]

    segs = cad_tools._build_pressurized_segments(
        qs=qs,
        overrides_by_idx=overrides,
        params=params,
        has_source_data=True,
        segment_name_fn=lambda idx: f"S{idx}",
    )

    assert len(segs) == 4
    assert [s["name"] for s in segs] == ["管道A-S1", "管道B-S1", "管道A-S2", "管道B-S2"]
    assert segs[0]["Q"] == 2.0 and segs[2]["Q"] == 1.0
    assert segs[0]["DN_mm"] == 1800 and segs[1]["DN_mm"] == 1600
    assert segs[0]["pipe_material"] == "钢管"
    assert segs[2]["n"] == 0.013


def test_build_pressurized_segments_dedup_same_signature_by_flow_segment():
    qs = [4.5, 4.3, 4.0]
    overrides = {
        1: {"name": "第一流量段", "n": 0.014},
        2: {"name": "第二流量段", "n": 0.014},
        3: {"name": "第三流量段", "n": 0.014},
    }
    params = [
        ("倒虹吸A", "球墨铸铁管", 1600),
        ("倒虹吸B", "球墨铸铁管", 1600),
        ("倒虹吸C", "球墨铸铁管", 1600),
    ]

    segs = cad_tools._build_pressurized_segments(
        qs=qs,
        overrides_by_idx=overrides,
        params=params,
        has_source_data=True,
        segment_name_fn=lambda idx: f"S{idx}",
    )

    assert len(segs) == 3
    assert [s["name"] for s in segs] == ["S1", "S2", "S3"]
    assert [s["Q"] for s in segs] == qs
    assert all(s["DN_mm"] == 1600 for s in segs)
    assert all(s["pipe_material"] == "球墨铸铁管" for s in segs)
    assert all(s["n"] == 0.014 for s in segs)


def test_build_pressurized_segments_keeps_prefix_when_same_flow_diff_signature():
    qs = [4.5]
    overrides = {1: {"name": "第二流量段", "n": 0.014}}
    params = [
        ("倒虹吸A", "球墨铸铁管", 1800),
        ("倒虹吸B", "钢管", 1800),
    ]

    segs = cad_tools._build_pressurized_segments(
        qs=qs,
        overrides_by_idx=overrides,
        params=params,
        has_source_data=True,
        segment_name_fn=lambda idx: f"S{idx}",
    )

    assert len(segs) == 2
    assert [s["name"] for s in segs] == ["倒虹吸A-S1", "倒虹吸B-S1"]
    assert [s["pipe_material"] for s in segs] == ["球墨铸铁管", "钢管"]


def test_build_pressurized_segments_does_not_overwrite_display_name_from_overrides():
    segs = cad_tools._build_pressurized_segments(
        qs=[2.0],
        overrides_by_idx={1: {"name": "第二流量段", "n": 0.012}},
        params=[("倒虹吸A", "球墨铸铁管", 1600)],
        has_source_data=True,
        segment_name_fn=lambda idx: f"S{idx}",
    )

    assert len(segs) == 1
    assert segs[0]["name"] == "S1"
    assert segs[0]["n"] == 0.012


def test_pressure_pipe_follows_siphon_summary_rules():
    segs = [{"name": "第一流量段", "Q": 2.0, "DN_mm": 1800, "pipe_material": "钢管"}]

    siphon_rows = summary_mod.compute_siphon(segs)
    pressure_rows = summary_mod.compute_pressure_pipe(segs)
    assert siphon_rows == pressure_rows

    _, siphon_headers, _, siphon_table_rows, _ = summary_mod._dxf_build_siphon(siphon_rows)
    _, pressure_headers, _, pressure_table_rows, _ = summary_mod._dxf_build_pressure_pipe(pressure_rows)
    assert siphon_headers == pressure_headers
    assert siphon_table_rows == pressure_table_rows
