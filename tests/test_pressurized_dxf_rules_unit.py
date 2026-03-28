# -*- coding: utf-8 -*-
"""有压流导出规则（倒虹吸 / 有压管道）单元测试。"""

import os
from pathlib import Path
import importlib.util
import importlib
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


def _load_summary_module():
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    matches = [p for p in root.glob("*/*.py") if p.name == "生成断面汇总表.py"]
    assert matches, "未找到 生成断面汇总表.py"
    spec = importlib.util.spec_from_file_location("summary_table_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


summary_mod = _load_summary_module()


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _dialog_shell(**attrs):
    dlg = cad_tools.SectionSummaryDialog.__new__(cad_tools.SectionSummaryDialog)
    for key, value in attrs.items():
        setattr(dlg, key, value)
    return dlg


def _node(
    *,
    structure_type,
    name="",
    d=0.0,
    h=0.0,
    flow_section="",
    is_siphon=False,
    is_pressure_pipe=False,
    is_transition=False,
    is_auto=False,
    pipe_material=None,
    velocity=None,
    head_loss_siphon=None,
    external_head_loss=None,
    section_params_extra=None,
):
    section_params = {"D": d} if d else {}
    if pipe_material is not None:
        section_params["pipe_material"] = pipe_material
    if section_params_extra:
        section_params.update(section_params_extra)
    return SimpleNamespace(
        is_transition=is_transition,
        is_auto_inserted_channel=is_auto,
        is_inverted_siphon=is_siphon,
        is_pressure_pipe=is_pressure_pipe,
        structure_type=SimpleNamespace(value=structure_type),
        name=name,
        flow_section=flow_section,
        section_params=section_params,
        structure_height=h,
        velocity=velocity,
        head_loss_siphon=head_loss_siphon,
        external_head_loss=external_head_loss,
    )


def _pressurized_row(name, flow_section, material, dn_mm, structure_kind="siphon"):
    return cad_tools._make_pressurized_param_row(
        name=name,
        flow_section=flow_section,
        structure_kind=structure_kind,
        pipe_material=material,
        dn_mm=dn_mm,
    )


def test_parse_positive_dn():
    assert cad_tools._parse_positive_dn("1500") == 1500
    assert cad_tools._parse_positive_dn("1500.0") == 1500
    assert cad_tools._parse_positive_dn("1500.5") is None
    assert cad_tools._parse_positive_dn("-1") is None
    assert cad_tools._parse_positive_dn("abc") is None


def test_extract_pressurized_param_entities_tracks_flow_sections_and_invalid_rows():
    nodes = [
        _node(structure_type="倒虹吸", name="龙王沟", d=0.85, flow_section="1", is_siphon=True),
        _node(structure_type="倒虹吸", name="", h=0.60, flow_section="第二流量段", is_siphon=True),
        _node(structure_type="倒虹吸", name="缺段倒虹吸", d=0.70, flow_section="", is_siphon=True),
        _node(structure_type="有压管道", name="1号管道", d=1.20, flow_section="3"),
    ]

    siphon_rows, invalid_rows = cad_tools._extract_pressurized_param_entities(nodes, "siphon")
    pressure_rows, pressure_invalid = cad_tools._extract_pressurized_param_entities(nodes, "pressure_pipe")

    assert [row["display_name"] for row in siphon_rows] == ["龙王沟-第一流量段", "未命名倒虹吸-第二流量段"]
    assert [row["flow_section"] for row in siphon_rows] == [1, 2]
    assert [row["DN_mm"] for row in siphon_rows] == [850, 600]
    assert invalid_rows == [
        {
            "name": "缺段倒虹吸",
            "display_name": "缺段倒虹吸",
            "structure_kind": "siphon",
        }
    ]
    assert [row["display_name"] for row in pressure_rows] == ["1号管道-第三流量段"]
    assert pressure_rows[0]["DN_mm"] == 1200
    assert pressure_invalid == []


def test_extract_pressurized_param_entities_preserves_locked_material_and_results():
    nodes = [
        _node(
            structure_type="倒虹吸",
            name="锁定倒虹吸",
            d=0.90,
            flow_section="1",
            is_siphon=True,
            pipe_material="钢管",
            velocity=1.236,
            head_loss_siphon=0.4821,
        ),
        _node(
            structure_type="有压管道",
            name="锁定有压管道",
            d=1.20,
            flow_section="2",
            is_pressure_pipe=True,
            pipe_material="玻璃钢夹砂管",
            velocity=1.458,
            external_head_loss=0.7314,
        ),
    ]

    siphon_rows, _ = cad_tools._extract_pressurized_param_entities(nodes, "siphon")
    pressure_rows, _ = cad_tools._extract_pressurized_param_entities(nodes, "pressure_pipe")

    assert siphon_rows[0]["pipe_material"] == "钢管"
    assert siphon_rows[0]["V"] == 1.236
    assert siphon_rows[0]["total_head_loss"] == 0.4821
    assert pressure_rows[0]["pipe_material"] == "玻璃钢夹砂管"
    assert pressure_rows[0]["V"] == 1.458
    assert pressure_rows[0]["total_head_loss"] == 0.7314


def test_merge_pressurized_param_defaults_migrates_legacy_name_cache_to_actual_segments():
    groups = [
        _pressurized_row("同名倒虹吸", 1, "球墨铸铁管", 850),
        _pressurized_row("同名倒虹吸", 2, "球墨铸铁管", 850),
    ]
    cached = [("同名倒虹吸", "钢管", 900)]

    merged = cad_tools._merge_pressurized_param_defaults(groups, cached)

    assert [row["display_name"] for row in merged] == ["同名倒虹吸-第一流量段", "同名倒虹吸-第二流量段"]
    assert [row["flow_section"] for row in merged] == [1, 2]
    assert [row["pipe_material"] for row in merged] == ["钢管", "钢管"]
    assert [row["DN_mm"] for row in merged] == [900, 900]


def test_build_pressurized_segments_example4_shape_uses_real_segment_mapping():
    qs = [1.1, 0.48]
    overrides = {1: {"n": 0.014}, 2: {"n": 0.014}}
    params = [
        _pressurized_row("龙王沟", 1, "球墨铸铁管", 850),
        _pressurized_row("催龙村", 2, "球墨铸铁管", 600),
        _pressurized_row("毡子坝", 2, "球墨铸铁管", 600),
        _pressurized_row("李家祠堂", 2, "球墨铸铁管", 600),
        _pressurized_row("皂角村", 2, "球墨铸铁管", 600),
    ]

    segs = cad_tools._build_pressurized_segments(
        qs=qs,
        overrides_by_idx=overrides,
        params=params,
        has_source_data=True,
        segment_name_fn=cad_tools._segment_label_from_index,
    )

    assert len(segs) == 5
    assert [seg["name"] for seg in segs] == [
        "龙王沟-第一流量段",
        "催龙村-第二流量段",
        "毡子坝-第二流量段",
        "李家祠堂-第二流量段",
        "皂角村-第二流量段",
    ]
    assert [seg["Q"] for seg in segs] == [1.1, 0.48, 0.48, 0.48, 0.48]
    assert [seg["DN_mm"] for seg in segs] == [850, 600, 600, 600, 600]
    assert all(seg["pipe_material"] == "球墨铸铁管" for seg in segs)


def test_build_pressurized_segments_single_building_segment_keeps_building_name():
    segs = cad_tools._build_pressurized_segments(
        qs=[2.0],
        overrides_by_idx={1: {"n": 0.012}},
        params=[_pressurized_row("单体倒虹吸", 1, "球墨铸铁管", 1600)],
        has_source_data=True,
        segment_name_fn=cad_tools._segment_label_from_index,
    )

    assert len(segs) == 1
    assert segs[0]["name"] == "单体倒虹吸-第一流量段"
    assert segs[0]["n"] == 0.012


def test_build_pressurized_segments_all_same_in_segment_keeps_each_structure_name():
    segs = cad_tools._build_pressurized_segments(
        qs=[4.5],
        overrides_by_idx={1: {"n": 0.014}},
        params=[
            _pressurized_row("倒虹吸A", 1, "球墨铸铁管", 1600),
            _pressurized_row("倒虹吸B", 1, "球墨铸铁管", 1600),
            _pressurized_row("倒虹吸C", 1, "球墨铸铁管", 1600),
        ],
        has_source_data=True,
        segment_name_fn=cad_tools._segment_label_from_index,
    )

    assert len(segs) == 3
    assert [seg["name"] for seg in segs] == [
        "倒虹吸A-第一流量段",
        "倒虹吸B-第一流量段",
        "倒虹吸C-第一流量段",
    ]
    assert all(seg["DN_mm"] == 1600 for seg in segs)


def test_build_pressurized_segments_multi_signature_segment_keeps_building_names():
    mat_a, mat_b = list(summary_mod.SIPHON_MATERIALS)[:2]
    segs = cad_tools._build_pressurized_segments(
        qs=[1.1],
        overrides_by_idx={1: {"n": 0.014}},
        params=[
            _pressurized_row("A", 1, mat_a, 850),
            _pressurized_row("B", 1, mat_a, 600),
            _pressurized_row("C", 1, mat_b, 600),
            _pressurized_row("D", 1, mat_a, 600),
        ],
        has_source_data=True,
        segment_name_fn=cad_tools._segment_label_from_index,
    )

    assert len(segs) == 4
    assert [seg["name"] for seg in segs] == [
        "A-第一流量段",
        "B-第一流量段",
        "C-第一流量段",
        "D-第一流量段",
    ]
    assert [seg["DN_mm"] for seg in segs] == [850, 600, 600, 600]
    assert [seg["pipe_material"] for seg in segs] == [mat_a, mat_a, mat_b, mat_a]


def test_build_pressurized_segments_skips_rows_without_matching_flow_section():
    segs = cad_tools._build_pressurized_segments(
        qs=[2.0],
        overrides_by_idx={1: {"n": 0.012}},
        params=[
            _pressurized_row("缺段", None, "球墨铸铁管", 1600),
            _pressurized_row("有效", 1, "球墨铸铁管", 1200),
        ],
        has_source_data=True,
        segment_name_fn=cad_tools._segment_label_from_index,
    )

    assert len(segs) == 1
    assert segs[0]["name"] == "有效-第一流量段"
    assert segs[0]["DN_mm"] == 1200


def test_build_pressurized_segments_returns_empty_for_unmapped_dict_rows():
    segs = cad_tools._build_pressurized_segments(
        qs=[2.0, 1.5],
        overrides_by_idx={},
        params=[_pressurized_row("占位", None, "球墨铸铁管", 1600)],
        has_source_data=True,
        segment_name_fn=cad_tools._segment_label_from_index,
    )

    assert segs == []


def test_build_pressurized_segments_preserves_locked_velocity_and_total_loss():
    segs = cad_tools._build_pressurized_segments(
        qs=[2.0],
        overrides_by_idx={1: {"n": 0.012}},
        params=[
            {
                **_pressurized_row("锁定有压管道", 1, "球墨铸铁管", 1600, structure_kind="pressure_pipe"),
                "V": 1.357,
                "total_head_loss": 0.5627,
            }
        ],
        has_source_data=True,
        segment_name_fn=cad_tools._segment_label_from_index,
    )

    assert len(segs) == 1
    assert segs[0]["V"] == 1.357
    assert segs[0]["total_head_loss"] == 0.5627


def test_siphon_dxf_header_uses_structure_name_and_flow_section():
    rows = summary_mod.compute_siphon([
        {"name": "龙王沟-第一流量段", "Q": 1.1, "DN_mm": 850, "pipe_material": "球墨铸铁管"}
    ])

    _, headers, _, table_rows, _ = summary_mod._dxf_build_siphon(rows)

    assert headers[0] == ("倒虹吸名称及流量段", None)
    assert headers[3] == ("糙率", None)
    assert table_rows[0][0] == "龙王沟-第一流量段"


def test_pressure_pipe_summary_uses_fmb_headers_and_locked_total_loss_only():
    rows = summary_mod.compute_pressure_pipe([{
        "name": "有压A-第一流量段",
        "Q": 1.1,
        "DN_mm": 850,
        "pipe_material": "球墨铸铁管",
        "V": 1.624,
        "total_head_loss": 0.4382,
        "ip_points": [
            {"x": 0.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
            {"x": 120.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
        ],
    }])

    assert rows[0]["friction_params"] == "223200 / 1.852 / 4.87"
    assert rows[0]["V"] == 1.624
    assert rows[0]["total_head_loss"] == 0.4382

    _, headers, _, table_rows, _ = summary_mod._dxf_build_pressure_pipe(rows)
    assert headers[0] == ("有压管道名称及流量段", None)
    assert headers[3] == ("摩阻参数f/m/b", None)
    assert headers[-1] == ("总水头损失", "m")
    assert table_rows[0][0] == "有压A-第一流量段"
    assert table_rows[0][3] == "223200 / 1.852 / 4.87"
    assert table_rows[0][4] == 850
    assert table_rows[0][-2] == 1.624
    assert table_rows[0][-1] == 0.4382


def test_pressure_pipe_summary_uses_dash_when_total_loss_missing():
    rows = summary_mod.compute_pressure_pipe([
        {
            "name": "有压B-第一流量段",
            "Q": 1.1,
            "DN_mm": 850,
            "pipe_material": "球墨铸铁管",
            "ip_points": [
                {"x": 0.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
                {"x": 120.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
            ],
            "upstream_velocity": 0.8,
            "downstream_velocity": 0.7,
        }
    ])

    assert rows[0]["V"] == "-"
    assert rows[0]["total_head_loss"] == "-"

    _, _, _, table_rows, _ = summary_mod._dxf_build_pressure_pipe(rows)
    assert table_rows[0][-2] == "-"
    assert table_rows[0][-1] == "-"


def test_siphon_summary_uses_dash_when_velocity_missing():
    rows = summary_mod.compute_siphon([
        {"name": "倒虹吸A-第一流量段", "Q": 1.1, "DN_mm": 850, "pipe_material": "球墨铸铁管"}
    ])

    assert rows[0]["V"] == "-"

    _, _, _, table_rows, _ = summary_mod._dxf_build_siphon(rows)
    assert table_rows[0][-1] == "-"


def test_siphon_summary_uses_locked_velocity_when_present():
    rows = summary_mod.compute_siphon([
        {"name": "倒虹吸A-第一流量段", "Q": 1.1, "DN_mm": 850, "pipe_material": "球墨铸铁管", "V": 1.426}
    ])

    assert rows[0]["V"] == 1.426

    _, _, _, table_rows, _ = summary_mod._dxf_build_siphon(rows)
    assert table_rows[0][-1] == 1.426


def test_section_summary_dialog_backfills_pressure_pipe_total_loss_from_panel_results():
    dlg = _dialog_shell(
        _panel=SimpleNamespace(
            get_pressure_pipe_export_results=lambda rows=None: {
                "1::牛马道": {"total_head_loss": 2.468, "source": "manager"}
            }
        )
    )
    rows = [
        {
            "name": "牛马道",
            "flow_section": 1,
            "Q": 3.0,
            "DN_mm": 1600,
            "pipe_material": "球墨铸铁管",
        }
    ]

    attached = cad_tools.SectionSummaryDialog._attach_pressure_pipe_export_results(dlg, rows)
    computed = summary_mod.compute_pressure_pipe(attached)

    assert attached[0]["total_head_loss"] == 2.468
    assert computed[0]["total_head_loss"] == 2.468


def test_serialize_pressurized_cache_rows_preserves_pressure_pipe_total_loss_and_context():
    rows = [
        {
            "name": "牛马道",
            "flow_section": 3,
            "display_name": "牛马道-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 1600,
            "structure_kind": "pressure_pipe",
            "total_head_loss": 0.5627,
            "ip_points": [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
            "upstream_velocity": 0.8,
            "downstream_velocity": 0.7,
            "inlet_transition_form": "反弯扭曲面",
            "outlet_transition_form": "反弯扭曲面",
        }
    ]

    serialized = cad_tools._serialize_pressurized_cache_rows(rows, "pressure_pipe")

    assert serialized[0]["total_head_loss"] == 0.5627
    assert serialized[0]["ip_points"] == [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}]
    assert serialized[0]["upstream_velocity"] == 0.8
    assert serialized[0]["outlet_transition_form"] == "反弯扭曲面"


def test_prepare_pressure_pipe_export_rows_uses_panel_results_for_cached_rows():
    rows = [
        {
            "name": "牛马道",
            "flow_section": 3,
            "display_name": "牛马道-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 1600,
            "structure_kind": "pressure_pipe",
        }
    ]
    panel = SimpleNamespace(
        get_pressure_pipe_export_results=lambda export_rows=None: {
            "3::牛马道": {"total_head_loss": 0.5627, "source": "table3"}
        }
    )

    prepared = cad_tools._prepare_pressure_pipe_export_rows(rows, panel=panel, calc_contexts={})

    assert prepared[0]["total_head_loss"] == 0.5627


def test_prepare_pressure_pipe_export_rows_uses_panel_velocity_for_cached_rows():
    rows = [
        {
            "name": "牛马道",
            "flow_section": 3,
            "display_name": "牛马道-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 1600,
            "structure_kind": "pressure_pipe",
        }
    ]
    panel = SimpleNamespace(
        get_pressure_pipe_export_results=lambda export_rows=None: {
            "3::牛马道": {"pipe_velocity": 1.438, "total_head_loss": 0.5627, "source": "table3"}
        }
    )

    prepared = cad_tools._prepare_pressure_pipe_export_rows(rows, panel=panel, calc_contexts={})

    assert prepared[0]["V"] == 1.438
    assert prepared[0]["total_head_loss"] == 0.5627


def test_draw_section_summary_on_msp_uses_panel_backfilled_pressure_pipe_total_loss(monkeypatch):
    actual_summary = importlib.import_module("calc_渠系计算算法内核.生成断面汇总表")
    captured = {}

    def _fake_draw_table(msp, x0, y0, title, headers, col_widths, rows, merge_groups=None, layer="0"):
        _ = (msp, x0, y0, title, headers, col_widths, merge_groups, layer)
        captured[title] = rows
        return 100.0

    monkeypatch.setattr(actual_summary, "_dxf_draw_table", _fake_draw_table)

    panel = SimpleNamespace(
        _custom_struct_thickness=None,
        _custom_rock_lining=None,
        _custom_tunnel_unified={},
        get_pressure_pipe_export_results=lambda rows=None: {
            "3::牛马道": {"total_head_loss": 0.5627, "source": "table3"}
        },
    )
    nodes = [
        SimpleNamespace(
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=True,
            structure_type=SimpleNamespace(value="有压管道"),
            name="牛马道",
            flow_section="3",
            flow=3.0,
            roughness=0.014,
            slope_i=0.0,
            section_params={"D": 1.6},
            water_depth=0.0,
            velocity=1.49,
            structure_height=1.6,
            x=0.0,
            y=0.0,
            turn_radius=0.0,
            turn_angle=0.0,
            in_out=None,
        ),
    ]
    pressurized_params = {
        "siphon": [],
        "pressure_pipe": cad_tools._serialize_pressurized_cache_rows(
            [
                {
                    "name": "牛马道",
                    "flow_section": 3,
                    "display_name": "牛马道-第三流量段",
                    "pipe_material": "球墨铸铁管",
                    "DN_mm": 1600,
                    "structure_kind": "pressure_pipe",
                }
            ],
            "pressure_pipe",
        ),
    }

    cad_tools._draw_section_summary_on_msp(
        panel=panel,
        msp=object(),
        nodes=nodes,
        proj_settings=None,
        pressurized_params=pressurized_params,
        below_y=0.0,
        summary_layer="SUMMARY",
    )

    pressure_rows = captured["有压管道断面尺寸及水力要素表"]
    assert pressure_rows[0][-1] == 0.5627


def test_build_horseshoe_export_entries_splits_mixed_section_types():
    entries = summary_mod._build_horseshoe_export_entries(
        [
            {"name": "马蹄Ⅰ-第一流量段", "Q": 2.0, "n": 0.014, "slope_inv": 1500, "horseshoe_section_type": 1, "R": 1.8},
            {"name": "马蹄Ⅱ-第二流量段", "Q": 1.5, "n": 0.014, "slope_inv": 1800, "horseshoe_section_type": 2, "R": 2.2},
        ],
        rock_lining=None,
        unified=False,
    )

    assert [entry["key"] for entry in entries] == ["tunnel_horseshoe_1", "tunnel_horseshoe_2"]
    assert entries[0]["title"].startswith("马蹄形标准Ⅰ型")
    assert entries[1]["title"].startswith("马蹄形标准Ⅱ型")
    assert entries[0]["sheet_name"].startswith("马蹄形标准Ⅰ型")
    assert entries[1]["sheet_name"].startswith("马蹄形标准Ⅱ型")


def test_collect_siphon_missing_velocity_labels_uses_dash_rows():
    dlg = _dialog_shell()

    labels = cad_tools.SectionSummaryDialog._collect_siphon_missing_velocity_labels(
        dlg,
        [{"name": "缺流速-第一流量段", "Q": 1.0, "DN_mm": 1000, "pipe_material": "球墨铸铁管"}],
    )

    assert labels == ["缺流速-第一流量段"]


def test_collect_siphon_missing_velocity_labels_skips_rows_with_valid_velocity():
    dlg = _dialog_shell()

    labels = cad_tools.SectionSummaryDialog._collect_siphon_missing_velocity_labels(
        dlg,
        [{"name": "已算流速-第一流量段", "V": 1.238}],
    )

    assert labels == []


def test_pressure_pipe_summary_maps_legacy_material_names_to_fmb():
    rows = summary_mod.compute_pressure_pipe([
        {"name": "PCCP-第一流量段", "Q": 1.0, "DN_mm": 1000, "pipe_material": "PCCP管"},
        {"name": "钢筋砼-第一流量段", "Q": 1.0, "DN_mm": 1000, "pipe_material": "钢筋混凝土管"},
    ])

    assert rows[0]["friction_params"] == "1312000 / 2 / 5.33"
    assert rows[1]["friction_params"] == "1312000 / 2 / 5.33"
    assert rows[0]["pipe_material"] == "预应力钢筒混凝土管(n=0.013)"
    assert rows[1]["pipe_material"] == "预应力钢筒混凝土管(n=0.013)"


def test_pressure_pipe_material_helpers_normalize_legacy_names_to_canonical_key_and_display():
    assert summary_mod.normalize_pressure_pipe_material_key("PCCP管") == "预应力钢筒混凝土管"
    assert summary_mod.normalize_pressure_pipe_material_key("钢筋混凝土管") == "预应力钢筒混凝土管"
    assert summary_mod.normalize_pressure_pipe_material_key("预应力钢筒混凝土管(n=0.014)") == "预应力钢筒混凝土管_n014"
    assert summary_mod.get_pressure_pipe_material_display_name("预应力钢筒混凝土管_n015") == "预应力钢筒混凝土管(n=0.015)"


def test_rect_channel_dxf_builder_hides_increase_columns_when_all_rows_disable_increase():
    title, headers, _col_widths, rows, _merge = summary_mod._dxf_build_rect_channel(
        [
            {
                "name": "第一流量段",
                "Q": 1.0,
                "Q_inc": 1.25,
                "slope_inv": 2000,
                "n": 0.014,
                "B": 1.5,
                "H": 1.39,
                "t": 0.3,
                "tie_rod": "0.2×0.2",
                "H1": 0.789,
                "H2": 0.936,
                "V": 0.845,
                "use_increase": False,
            }
        ]
    )

    assert title == "矩形明渠断面尺寸及水力要素表"
    assert [name for name, _unit in headers] == [
        "流量段", "设计流量", "1/底坡", "糙率", "底宽B", "高度H",
        "壁厚t", "拉杆尺寸", "设计水深H₁", "设计流速",
    ]
    assert rows == [[
        "第一流量段", 1.0, "1/2000", 0.014, 1.5, 1.39, 0.3, "0.2×0.2", 0.789, 0.845
    ]]


def test_rect_channel_dxf_builder_keeps_increase_columns_for_mixed_rows_but_blanks_disabled_values():
    _title, headers, _col_widths, rows, _merge = summary_mod._dxf_build_rect_channel(
        [
            {
                "name": "第一流量段",
                "Q": 1.0,
                "Q_inc": 1.25,
                "slope_inv": 2000,
                "n": 0.014,
                "B": 1.5,
                "H": 1.39,
                "t": 0.3,
                "tie_rod": "0.2×0.2",
                "H1": 0.789,
                "H2": 0.936,
                "V": 0.845,
                "use_increase": False,
            },
            {
                "name": "第二流量段",
                "Q": 2.0,
                "Q_inc": 2.5,
                "slope_inv": 1500,
                "n": 0.014,
                "B": 2.0,
                "H": 1.68,
                "t": 0.3,
                "tie_rod": "0.2×0.2",
                "H1": 1.032,
                "H2": 1.192,
                "V": 0.914,
                "use_increase": True,
            },
        ]
    )

    assert [name for name, _unit in headers] == [
        "流量段", "设计流量", "加大流量", "1/底坡", "糙率", "底宽B", "高度H",
        "壁厚t", "拉杆尺寸", "设计水深H₁", "加大水深H₂", "设计流速",
    ]
    assert rows[0] == [
        "第一流量段", 1.0, "", "1/2000", 0.014, 1.5, 1.39, 0.3, "0.2×0.2", 0.789, "", 0.845
    ]
    assert rows[1] == [
        "第二流量段", 2.0, 2.5, "1/1500", 0.014, 2.0, 1.68, 0.3, "0.2×0.2", 1.032, 1.192, 0.914
    ]


def test_write_rect_channel_hides_increase_columns_when_all_rows_disable_increase():
    openpyxl, styles, gcl = summary_mod._get_openpyxl()
    wb = openpyxl.Workbook()
    ws = wb.active

    ncols = summary_mod._write_rect_channel(
        ws,
        [
            {
                "name": "第一流量段",
                "Q": 1.0,
                "Q_inc": 1.25,
                "slope_inv": 2000,
                "n": 0.014,
                "B": 1.5,
                "H": 1.39,
                "t": 0.3,
                "tie_rod": "0.2×0.2",
                "H1": 0.789,
                "H2": 0.936,
                "V": 0.845,
                "use_increase": False,
            }
        ],
        styles,
        gcl,
    )

    assert ncols == 10
    assert ws.cell(1, 1).value == "矩形明渠断面尺寸及水力要素表"
    assert [ws.cell(2, c).value for c in range(1, 11)] == [
        "流量段", "设计流量", "1/底坡", "糙率", "底宽B", "高度H",
        "壁厚t", "拉杆尺寸", "设计水深H₁", "设计流速",
    ]
    assert [ws.cell(4, c).value for c in range(1, 11)] == [
        "第一流量段", 1.0, "1/2000", 0.014, 1.5, 1.39, 0.3, "0.2×0.2", 0.789, 0.845
    ]


def test_dxf_build_tunnel_hides_increase_columns_when_all_rows_disable_increase():
    title, headers, _col_widths, rows, merge = summary_mod._dxf_build_tunnel(
        [
            {
                "name": "第一流量段",
                "Q": 1.0,
                "Q_inc": 1.25,
                "rock_class": "III类",
                "slope_inv": 2000,
                "n": 0.014,
                "B": 1.8,
                "H_straight": 1.1,
                "R_arch": 0.9,
                "t0": 0.35,
                "t": 0.3,
                "H1": 0.662,
                "H2": 0.780,
                "V": 0.84,
                "use_increase": False,
            },
            {
                "name": "第一流量段",
                "Q": 1.0,
                "Q_inc": 1.25,
                "rock_class": "IV类",
                "slope_inv": 2000,
                "n": 0.014,
                "B": 1.8,
                "H_straight": 1.1,
                "R_arch": 0.9,
                "t0": 0.4,
                "t": 0.4,
                "H1": 0.662,
                "H2": 0.780,
                "V": 0.84,
                "use_increase": False,
            },
            {
                "name": "第一流量段",
                "Q": 1.0,
                "Q_inc": 1.25,
                "rock_class": "V类",
                "slope_inv": 2000,
                "n": 0.014,
                "B": 1.8,
                "H_straight": 1.1,
                "R_arch": 0.9,
                "t0": 0.5,
                "t": 0.5,
                "H1": 0.662,
                "H2": 0.780,
                "V": 0.84,
                "use_increase": False,
            },
        ]
    )

    assert title == "圆拱直墙型隧洞断面尺寸及水力要素表"
    assert [name for name, _unit in headers] == [
        "流量段", "设计流量", "围岩类型", "1/底坡", "糙率",
        "底宽B", "直墙高H", "顶拱半径R", "底板厚t₀", "边墙顶拱厚t",
        "设计水深H₁", "设计流速",
    ]
    assert rows[0] == [
        "第一流量段", 1.0, "III类", "1/2000", 0.014, 1.8, 1.1, 0.9, 0.35, 0.3, 0.662, 0.84
    ]
    assert merge == [([0, 1], 3)]


def test_write_tunnel_hides_increase_columns_when_all_rows_disable_increase():
    openpyxl, styles, gcl = summary_mod._get_openpyxl()
    wb = openpyxl.Workbook()
    ws = wb.active

    ncols = summary_mod._write_tunnel(
        ws,
        [
            {
                "name": "第一流量段",
                "Q": 1.0,
                "Q_inc": 1.25,
                "rock_class": "III类",
                "slope_inv": 2000,
                "n": 0.014,
                "B": 1.8,
                "H_straight": 1.1,
                "R_arch": 0.9,
                "t0": 0.35,
                "t": 0.3,
                "H1": 0.662,
                "H2": 0.780,
                "V": 0.84,
                "use_increase": False,
            },
            {
                "name": "第一流量段",
                "Q": 1.0,
                "Q_inc": 1.25,
                "rock_class": "IV类",
                "slope_inv": 2000,
                "n": 0.014,
                "B": 1.8,
                "H_straight": 1.1,
                "R_arch": 0.9,
                "t0": 0.4,
                "t": 0.4,
                "H1": 0.662,
                "H2": 0.780,
                "V": 0.84,
                "use_increase": False,
            },
            {
                "name": "第一流量段",
                "Q": 1.0,
                "Q_inc": 1.25,
                "rock_class": "V类",
                "slope_inv": 2000,
                "n": 0.014,
                "B": 1.8,
                "H_straight": 1.1,
                "R_arch": 0.9,
                "t0": 0.5,
                "t": 0.5,
                "H1": 0.662,
                "H2": 0.780,
                "V": 0.84,
                "use_increase": False,
            },
        ],
        styles,
        gcl,
    )

    assert ncols == 12
    assert ws.cell(1, 1).value == "圆拱直墙型隧洞断面尺寸及水力要素表"
    assert [ws.cell(2, c).value for c in range(1, 13)] == [
        "流量段", "设计流量", "围岩类型", "1/底坡", "糙率",
        "底宽B", "直墙高H", "顶拱半径R", "底板厚t₀", "边墙顶拱厚t",
        "设计水深H₁", "设计流速",
    ]


def test_compute_rect_channel_adds_tie_rod_height_to_export_H(monkeypatch):
    captured_kwargs = []

    def _fake_rectangular(**_kwargs):
        captured_kwargs.append(dict(_kwargs))
        return {
            "success": True,
            "Q_increased": 1.25,
            "b_design": 1.5,
            "h_prime": 1.19,
            "h_design": 0.789,
            "h_increased": 0.936,
            "V_design": 0.845,
        }

    monkeypatch.setattr(summary_mod, "quick_calculate_rectangular", _fake_rectangular)

    rows = summary_mod.compute_rect_channel(
        [
            {
                "name": "第一流量段",
                "Q": 1.0,
                "slope_inv": 2000,
                "n": 0.014,
                "B": 1.5,
                "wall_t": 0.3,
                "tie_rod": "0.2×0.2",
            }
        ]
    )

    assert captured_kwargs
    assert captured_kwargs[0]["manual_b"] == 1.5
    assert captured_kwargs[0]["preserve_manual_b"] is True
    assert rows[0]["H"] == 1.39
    assert rows[0]["B"] == 1.5
    assert rows[0]["tie_rod"] == "0.2×0.2"


def test_compute_trapezoid_channel_adds_tie_rod_height_to_export_H(monkeypatch):
    captured_kwargs = []

    def _fake_trapezoidal(**_kwargs):
        captured_kwargs.append(dict(_kwargs))
        return {
            "success": True,
            "Q_increased": 1.25,
            "b_design": 1.5,
            "h_prime": 1.19,
            "h_design": 0.789,
            "h_increased": 0.936,
            "V_design": 0.845,
            "Beta_design": 1.902,
        }

    monkeypatch.setattr(summary_mod, "quick_calculate_trapezoidal", _fake_trapezoidal)

    rows = summary_mod.compute_trapezoid_channel(
        [
            {
                "name": "第一流量段",
                "Q": 1.0,
                "slope_inv": 2000,
                "n": 0.014,
                "m": 1.0,
                "B": 1.5,
                "wall_t": 0.3,
                "tie_rod": "0.2 X 0.2",
            }
        ]
    )

    assert captured_kwargs
    assert captured_kwargs[0]["manual_b"] == 1.5
    assert captured_kwargs[0]["preserve_manual_b"] is True
    assert rows[0]["H"] == 1.39
    assert rows[0]["B"] == 1.5
    assert rows[0]["tie_rod"] == "0.2 X 0.2"


def test_build_q_segment_structure_names_distinguishes_same_name_cross_types():
    dlg = _dialog_shell(
        _segment_count=2,
        _nodes=[
            _node(structure_type="倒虹吸", name="龙王沟", flow_section="1", is_siphon=True),
            _node(structure_type="倒虹吸", name="龙王沟", flow_section="1", is_siphon=True),
            _node(structure_type="有压管道", name="龙王沟", flow_section="1", is_pressure_pipe=True),
            _node(structure_type="有压管道", name="新建管道", flow_section="2", is_pressure_pipe=True),
        ],
    )

    names = cad_tools.SectionSummaryDialog._build_q_segment_structure_names(dlg)

    assert names[1] == ["龙王沟（倒虹吸）", "龙王沟（有压管道）"]
    assert names[2] == ["新建管道"]


def test_build_q_segment_label_uses_type_suffix_for_same_name_cross_types():
    dlg = _dialog_shell(
        _q_segment_structure_names={1: ["Longwanggou (siphon)", "Longwanggou (pressure pipe)", "Backup pipe"]},
        _segment_name=lambda idx: f"SEG-{idx}",
    )

    parts = cad_tools.SectionSummaryDialog._build_q_segment_label(dlg, 1)

    assert parts["segment_title"] == "SEG-1"
    assert parts["names_text"] == "Longwanggou (siphon), Longwanggou (pressure pipe), Backup pipe"
    assert parts["tooltip_text"] == "Longwanggou (siphon), Longwanggou (pressure pipe), Backup pipe"
    assert "等" not in parts["names_text"]


def test_block_invalid_pressurized_export_returns_true_and_emits_error(monkeypatch):
    captured = {}

    def _fake_error(parent, title, content):
        captured["title"] = title
        captured["content"] = content

    monkeypatch.setattr(cad_tools, "fluent_error", _fake_error)
    dlg = _dialog_shell(
        _invalid_siphon_groups=[{"display_name": "缺段倒虹吸"}],
        _invalid_pressure_pipe_groups=[{"display_name": "缺段有压管道"}],
        _invalid_pressurized_notice_shown=False,
    )

    blocked = cad_tools.SectionSummaryDialog._block_invalid_pressurized_export(dlg)

    assert blocked is True
    assert captured["title"] == "无法导出"
    assert "缺段倒虹吸" in captured["content"]
    assert "缺段有压管道" in captured["content"]


def test_collect_pressure_pipe_missing_total_head_loss_labels_uses_dash_rows():
    dlg = _dialog_shell(
        _compute_pressure_pipe=summary_mod.compute_pressure_pipe,
    )

    labels = cad_tools.SectionSummaryDialog._collect_pressure_pipe_missing_total_head_loss_labels(
        dlg,
        [{"name": "缺损失-第一流量段", "Q": 1.0, "DN_mm": 1000, "pipe_material": "球墨铸铁管"}],
    )

    assert labels == ["缺损失-第一流量段"]


def test_section_summary_dialog_q_grid_uses_compact_two_column_form_layout():
    _get_qapp()
    dlg = cad_tools.SectionSummaryDialog(None, [], None, config_only=True)

    assert dlg._q_form_grid.columnMinimumWidth(0) == dlg._ui_name_column_min_width
    assert dlg._q_form_grid.columnMinimumWidth(1) == dlg._ui_q_value_column_width
    assert dlg._q_form_grid.columnStretch(0) == 1
    assert dlg._q_form_grid.columnStretch(1) == 0
    assert dlg._q_edits[0].minimumWidth() == dlg._ui_q_value_column_width
    row_widget = dlg._q_form_grid.itemAtPosition(0, 0).widget()
    assert row_widget.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert isinstance(row_widget._segment_title_label, QLabel)
    assert row_widget._segment_names_label is None

    dlg.deleteLater()


def test_build_q_segment_row_widget_uses_separate_title_and_two_line_name_label():
    _get_qapp()
    dlg = _dialog_shell(
        _q_segment_structure_names={
            2: ["Cuicun", "Zuzi", "Lijiatang", "Zhuojiawan", "Miaowan", "Yaojiawan"]
        },
        _segment_name=lambda idx: f"SEG-{idx}",
        _styled_q_segment_title_label=lambda text: cad_tools.SectionSummaryDialog._styled_q_segment_title_label(
            _dialog_shell(), text
        ),
    )
    dlg._styled_name_value_label = lambda text, tooltip_text="", max_lines=None: cad_tools.SectionSummaryDialog._styled_name_value_label(
        _dialog_shell(), text, tooltip_text=tooltip_text, max_lines=max_lines
    )

    row_widget = cad_tools.SectionSummaryDialog._build_q_segment_row_widget(dlg, 2)

    assert isinstance(row_widget._segment_title_label, QLabel)
    assert row_widget._segment_title_label.text() == "SEG-2"
    assert isinstance(row_widget._segment_names_label, cad_tools._MultiLineElidedLabel)
    assert row_widget._segment_names_label.toolTip() == "Cuicun, Zuzi, Lijiatang, Zhuojiawan, Miaowan, Yaojiawan"
    assert row_widget.layout().count() == 2

    row_widget.resize(320, 120)
    row_widget.show()
    _get_qapp().processEvents()
    assert row_widget._segment_names_label.text().count("\n") <= 1

    row_widget.deleteLater()


def test_multi_line_elided_label_uses_three_lines_and_tooltip_for_long_text():
    app = _get_qapp()
    label = cad_tools._MultiLineElidedLabel(
        "SEG-1 (LuRong, GuangYue, GuangGaolu, Niumadao, Shibanqiao, Zhangjiawan, Zhaojiahe, Liushuwan)",
        tooltip_text="LuRong, GuangYue, GuangGaolu, Niumadao, Shibanqiao, Zhangjiawan, Zhaojiahe, Liushuwan",
        max_lines=3,
    )
    label.resize(110, 200)
    label.show()
    app.processEvents()

    assert label.toolTip() == "LuRong, GuangYue, GuangGaolu, Niumadao, Shibanqiao, Zhangjiawan, Zhaojiahe, Liushuwan"
    assert label.text().count("\n") <= 2
    assert "等" not in label.text()
    assert "…" in label.text() or "..." in label.text()

    label.resize(520, 200)
    app.processEvents()
    assert "GuangGaolu" in label.text()
    assert "Niumadao" in label.text()

    label.deleteLater()


def test_multi_line_elided_label_recomputes_height_after_stylesheet_font_change():
    app = _get_qapp()
    label = cad_tools._MultiLineElidedLabel(
        "SEG-2 (Cuicun, Zuzi, Lijiatang, Zhuojiawan, Miaowan, Yaojiawan)",
        tooltip_text="Cuicun, Zuzi, Lijiatang, Zhuojiawan, Miaowan, Yaojiawan",
        max_lines=3,
    )
    label.resize(120, 200)
    label.show()
    app.processEvents()

    before_height = label.maximumHeight()
    label.setStyleSheet("font-size: 18px;")
    app.processEvents()

    expected_height = label.heightForWidth(label.width())
    assert label.maximumHeight() == expected_height
    assert label.minimumHeight() == expected_height
    assert expected_height >= before_height
    assert label.sizeHint().height() == expected_height
    assert label.minimumSizeHint().height() == expected_height

    label.deleteLater()


def test_section_summary_dialog_pressurized_grids_share_header_and_row_columns():
    _get_qapp()
    dlg = cad_tools.SectionSummaryDialog(None, [], None, config_only=True)

    for grid in (dlg._siphon_form_grid, dlg._pressure_pipe_form_grid):
        assert grid.columnMinimumWidth(0) == dlg._ui_name_column_min_width
        assert grid.columnMinimumWidth(1) == dlg._ui_material_column_width
        assert grid.columnMinimumWidth(2) == dlg._ui_dn_column_width
        assert isinstance(grid.itemAtPosition(0, 0).widget(), QLabel)
        assert grid.itemAtPosition(0, 1).widget().text() == "管道材质"
        assert grid.itemAtPosition(0, 2).widget().text() == "DN (mm)"

    siphon_mat = dlg._siphon_form_grid.itemAtPosition(1, 1).widget()
    siphon_dn = dlg._siphon_form_grid.itemAtPosition(1, 2).widget()
    pressure_mat = dlg._pressure_pipe_form_grid.itemAtPosition(1, 1).widget()
    pressure_dn = dlg._pressure_pipe_form_grid.itemAtPosition(1, 2).widget()

    assert siphon_mat.minimumWidth() == dlg._ui_material_column_width
    assert pressure_mat.minimumWidth() == dlg._ui_material_column_width
    assert siphon_dn.minimumWidth() == dlg._ui_dn_column_width
    assert pressure_dn.minimumWidth() == dlg._ui_dn_column_width

    dlg.deleteLater()


def test_section_summary_dialog_struct_tabs_reuse_same_form_alignment_rules():
    _get_qapp()
    dlg = cad_tools.SectionSummaryDialog(None, [], None, config_only=True)

    for grid, value_cols in (
        (dlg._struct_channel_grid, 2),
        (dlg._struct_aqueduct_grid, 1),
        (dlg._struct_culvert_grid, 3),
        (dlg._struct_tunnel_grid, 2),
    ):
        assert grid.columnMinimumWidth(0) == 120
        for ci in range(1, value_cols + 1):
            assert grid.columnMinimumWidth(ci) == dlg._ui_numeric_column_width

    assert dlg._rect_ch_wall_t.minimumWidth() == dlg._ui_numeric_column_width
    assert dlg._aq_u_wall_t.minimumWidth() == dlg._ui_numeric_column_width
    assert dlg._culvert_t0.minimumWidth() == dlg._ui_numeric_column_width

    dlg.deleteLater()

