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


def _load_panel_module():
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    matches = list(root.glob("*/water_profile/panel.py"))
    assert matches, "未找到 panel.py"
    spec = importlib.util.spec_from_file_location("panel_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


summary_mod = _load_summary_module()
panel_mod = _load_panel_module()


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _dialog_shell(**attrs):
    dlg = cad_tools.SectionSummaryDialog.__new__(cad_tools.SectionSummaryDialog)
    for key, value in attrs.items():
        setattr(dlg, key, value)
    return dlg


class _DummyCombo:
    def __init__(self, text):
        self._text = text

    def currentText(self):
        return self._text


class _DummyLineEdit:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


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


def test_merge_pressurized_param_defaults_preserves_pressure_pipe_flow_section_metadata():
    groups = [
        {
            "name": "",
            "flow_section": 1,
            "display_name": "第一流量段 第1行有压管道",
            "structure_kind": "pressure_pipe",
            "pipe_material": "HDPE管",
            "DN_mm": 400,
            "identity": "flow1-row1",
            "storage_key": "flow1-row1",
            "route_key": "route-main",
            "route_display_name": "主线",
            "plan_total_length": 1699.0,
            "Q": 0.1,
        }
    ]

    merged = cad_tools._merge_pressurized_param_defaults(groups, [])

    assert merged[0]["identity"] == "flow1-row1"
    assert merged[0]["storage_key"] == "flow1-row1"
    assert merged[0]["route_key"] == "route-main"
    assert merged[0]["route_display_name"] == "主线"
    assert merged[0]["plan_total_length"] == 1699.0
    assert merged[0]["Q"] == 0.1


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


def test_pressure_pipe_summary_hides_building_characteristics_when_all_counts_are_zero():
    rows = summary_mod.compute_pressure_pipe([{
        "name": "第一流量段",
        "Q": 3.0,
        "DN_mm": 1600,
        "pipe_material": "球墨铸铁管",
        "V": 1.624,
        "total_length": 1520.0,
        "total_head_loss": 0.4382,
        "start_water_level": 510.25,
        "end_water_level": 507.8,
        "ip_points": [
            {"x": 0.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
            {"x": 120.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
        ],
    }])

    assert rows[0]["friction_params"] == "223200 / 1.852 / 4.87"
    assert rows[0]["V"] == 1.624
    assert rows[0]["total_head_loss"] == 0.4382
    assert rows[0]["total_length"] == 1520.0

    title, headers, _, table_rows, _ = summary_mod._dxf_build_pressure_pipe(rows)
    assert title == "压力管道特性表"
    assert [name for name, _unit in headers] == [
        "流量段", "设计流量", "加大流量", "长度", "管材", "管径", "设计流速",
        "渠首水位", "渠末水位",
    ]
    assert headers[3] == ("长度", "km")
    assert headers[5] == ("管径", "m")
    assert headers[7] == ("渠首水位", "m")
    assert headers[8] == ("渠末水位", "m")
    assert table_rows[0][0] == "第一流量段"
    assert table_rows[0][3] == 1.52
    assert table_rows[0][4] == "球墨铸铁管"
    assert table_rows[0][5] == 1.6
    assert table_rows[0][6] == 1.624
    assert table_rows[0][7] == 510.25
    assert table_rows[0][8] == 507.8


def test_pressure_pipe_summary_shows_building_characteristics_groups_and_zero_values_as_dash():
    rows = summary_mod.compute_pressure_pipe([
        {
            "name": "第一流量段",
            "Q": 3.0,
            "DN_mm": 1600,
            "pipe_material": "球墨铸铁管",
            "V": 1.438,
            "total_length": 1520.0,
            "start_water_level": 512.3,
            "end_water_level": 509.7,
            "tunnel_count": 2,
            "tunnel_length": 1200.0,
            "directional_drill_count": 1,
            "directional_drill_length": 200.0,
            "jacking_count": 0,
            "jacking_length": 0.0,
            "show_building_characteristics": True,
        },
        {
            "name": "第二流量段",
            "Q": 2.0,
            "DN_mm": 1400,
            "pipe_material": "钢管",
            "V": 1.251,
            "total_length": 980.0,
            "start_water_level": 512.3,
            "end_water_level": 509.7,
            "tunnel_count": 0,
            "tunnel_length": 0.0,
            "directional_drill_count": 0,
            "directional_drill_length": 0.0,
            "jacking_count": 0,
            "jacking_length": 0.0,
            "show_building_characteristics": True,
        },
    ])

    _, headers, _, table_rows, merge = summary_mod._dxf_build_pressure_pipe(rows)

    assert [name for name, _unit in headers[-6:]] == [
        "隧洞座数", "隧洞长度（km）",
        "定向钻座数", "定向钻长度（km）",
        "顶管座数", "顶管长度（km）",
    ]
    assert merge["header_row_count"] == 3
    assert any(cell["text"] == "建筑物特性" for cell in merge["header_cells"])
    assert any(cell["text"] == "隧洞" for cell in merge["header_cells"])
    assert any(cell["text"] == "定向钻" for cell in merge["header_cells"])
    assert any(cell["text"] == "顶管" for cell in merge["header_cells"])
    assert table_rows[0][-6:] == [2, 1.2, 1, 0.2, "-", "-"]
    assert table_rows[1][-6:] == ["-", "-", "-", "-", "-", "-"]


def test_pressure_pipe_summary_uses_dash_when_length_and_velocity_missing():
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
    assert rows[0]["total_length"] == "-"

    _, _, _, table_rows, _ = summary_mod._dxf_build_pressure_pipe(rows)
    assert table_rows[0][3] == "-"
    assert table_rows[0][5] == 0.85
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


def test_read_pressurized_rows_preserves_identity_metadata_for_pressure_pipe():
    dlg = _dialog_shell(
        _current_pressure_pipe_material_value=lambda combo: combo.currentText(),
    )
    source_row = {
        "name": "",
        "flow_section": 2,
        "display_name": "未命名有压管道-第二流量段",
        "structure_kind": "pressure_pipe",
        "identity": "flow2-row6",
        "storage_key": "flow2-row6",
        "route_key": "route-main",
        "route_display_name": "主线",
        "plan_total_length": 1699.0,
    }

    result = cad_tools.SectionSummaryDialog._read_pressurized_rows(
        dlg,
        [(source_row, _DummyCombo("HDPE管"), _DummyLineEdit("400"))],
        "有压管道",
    )

    assert result[0]["identity"] == "flow2-row6"
    assert result[0]["storage_key"] == "flow2-row6"
    assert result[0]["route_key"] == "route-main"
    assert result[0]["route_display_name"] == "主线"
    assert result[0]["plan_total_length"] == 1699.0


def test_section_summary_dialog_extract_pressure_pipe_groups_prefers_panel_dialog_groups():
    dialog_group = SimpleNamespace(
        name="",
        rows=[SimpleNamespace(flow_section="第一流量段")],
        design_flow=0.1,
        diameter=0.4,
        material_key="HDPE管",
        group_mode="unnamed_row_segment",
        display_name="第一流量段 第1行有压管道",
        storage_key="flow1-row1",
        identity="flow1-row1",
        target_row_index=0,
        upstream_row_index=0,
        plan_total_length=1699.0,
        route_key="route-main",
        route_display_name="主线",
        route_start_row_index=0,
        route_end_row_index=10,
        route_start_mc=0.0,
        route_end_mc=1699.0,
        route_ip_points=[{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
        route_member_keys=["flow1-row1"],
        segment_start_mc=0.0,
        segment_end_mc=1699.0,
        ip_points=[{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
        upstream_velocity=0.42,
        downstream_velocity=0.38,
        inlet_transition_form="反弯扭曲面",
        outlet_transition_form="反弯扭曲面",
        inlet_transition_zeta=0.1,
        outlet_transition_zeta=0.2,
    )
    dlg = _dialog_shell(
        _panel=SimpleNamespace(
            _extract_pressure_pipe_dialog_groups=lambda nodes, settings=None: [dialog_group]
        ),
        _nodes=[],
        _proj_settings=SimpleNamespace(),
    )

    groups, invalid = cad_tools.SectionSummaryDialog._extract_pressure_pipe_groups(dlg)

    assert invalid == []
    assert groups[0]["flow_section"] == 1
    assert groups[0]["Q"] == 0.1
    assert groups[0]["pipe_material"] == "HDPE管"
    assert groups[0]["DN_mm"] == 400
    assert groups[0]["identity"] == "flow1-row1"
    assert groups[0]["plan_total_length"] == 1699.0
    assert groups[0]["route_key"] == "route-main"
    assert groups[0]["route_display_name"] == "主线"


def test_build_pressure_pipe_dialog_rows_collapses_flow_section_and_keeps_special_groups():
    raw_rows = [
        {
            "name": "未命名有压管道",
            "flow_section": 1,
            "display_name": "流量段1 第114行有压管道",
            "structure_kind": "pressure_pipe",
            "pipe_material": "HDPE管",
            "DN_mm": 400,
            "identity": "flow1-row114",
            "plan_total_length": 1699.0,
            "pressure_pipe_structure_type": "有压管道",
        },
        {
            "name": "未命名有压管道",
            "flow_section": 1,
            "display_name": "流量段1 第115行有压管道",
            "structure_kind": "pressure_pipe",
            "pipe_material": "HDPE管",
            "DN_mm": 400,
            "identity": "flow1-row115",
            "plan_total_length": 1699.0,
            "pressure_pipe_structure_type": "有压管道",
        },
        {
            "name": "磨盘寨",
            "flow_section": 1,
            "display_name": "磨盘寨",
            "structure_kind": "pressure_pipe",
            "pipe_material": "钢管",
            "DN_mm": 500,
            "identity": "flow1-mpz",
            "plan_total_length": 80.0,
            "pressure_pipe_structure_type": "定向钻",
        },
        {
            "name": "观音岩",
            "flow_section": 1,
            "display_name": "观音岩",
            "structure_kind": "pressure_pipe",
            "pipe_material": "钢管",
            "DN_mm": 450,
            "identity": "flow1-gyy",
            "plan_total_length": 60.0,
            "pressure_pipe_structure_type": "定向钻",
        },
    ]

    dialog_rows = cad_tools._build_pressure_pipe_dialog_rows(raw_rows, [])

    assert [row["display_name"] for row in dialog_rows] == ["第一流量段", "磨盘寨", "观音岩"]
    assert dialog_rows[0]["dialog_row_kind"] == "flow_section_pressure_pipe"
    assert dialog_rows[0]["dialog_target_identities"] == ["flow1-row114", "flow1-row115"]
    assert len(dialog_rows[0]["dialog_target_rows"]) == 2
    assert dialog_rows[1]["dialog_row_kind"] == "named_pressure_like_group"
    assert dialog_rows[1]["dialog_target_identities"] == ["flow1-mpz"]
    assert dialog_rows[2]["dialog_target_identities"] == ["flow1-gyy"]


def test_build_pressure_pipe_dialog_rows_keeps_flow_section_main_row_first_per_section():
    raw_rows = [
        {
            "name": "磨盘寨",
            "flow_section": 1,
            "display_name": "磨盘寨",
            "structure_kind": "pressure_pipe",
            "pipe_material": "钢管",
            "DN_mm": 500,
            "identity": "flow1-mpz",
            "pressure_pipe_structure_type": "定向钻",
        },
        {
            "name": "未命名有压管道",
            "flow_section": 1,
            "display_name": "流量段1 第10行有压管道",
            "structure_kind": "pressure_pipe",
            "pipe_material": "HDPE管",
            "DN_mm": 400,
            "identity": "flow1-row10",
            "pressure_pipe_structure_type": "有压管道",
        },
        {
            "name": "未命名有压管道",
            "flow_section": 2,
            "display_name": "流量段2 第20行有压管道",
            "structure_kind": "pressure_pipe",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 600,
            "identity": "flow2-row20",
            "pressure_pipe_structure_type": "有压管道",
        },
        {
            "name": "磨盘寨",
            "flow_section": 2,
            "display_name": "磨盘寨",
            "structure_kind": "pressure_pipe",
            "pipe_material": "钢管",
            "DN_mm": 520,
            "identity": "flow2-mpz",
            "pressure_pipe_structure_type": "顶管",
        },
    ]

    dialog_rows = cad_tools._build_pressure_pipe_dialog_rows(raw_rows, [])

    assert [row["display_name"] for row in dialog_rows] == [
        "第一流量段",
        "磨盘寨-第一流量段",
        "第二流量段",
        "磨盘寨-第二流量段",
    ]


def test_read_pressurized_rows_expands_flow_section_dialog_row_back_to_targets():
    dlg = _dialog_shell(
        _current_pressure_pipe_material_value=lambda combo: combo.currentText(),
    )
    dialog_row = {
        "name": "第一流量段",
        "flow_section": 1,
        "display_name": "第一流量段",
        "structure_kind": "pressure_pipe",
        "dialog_row_kind": "flow_section_pressure_pipe",
        "dialog_target_identities": ["flow1-row114", "flow1-row115"],
        "dialog_target_rows": [
            {
                "name": "未命名有压管道",
                "flow_section": 1,
                "display_name": "流量段1 第114行有压管道",
                "structure_kind": "pressure_pipe",
                "identity": "flow1-row114",
                "storage_key": "flow1-row114",
                "route_key": "route-main",
                "route_display_name": "主线",
                "plan_total_length": 1699.0,
                "pressure_pipe_structure_type": "有压管道",
            },
            {
                "name": "未命名有压管道",
                "flow_section": 1,
                "display_name": "流量段1 第115行有压管道",
                "structure_kind": "pressure_pipe",
                "identity": "flow1-row115",
                "storage_key": "flow1-row115",
                "route_key": "route-main",
                "route_display_name": "主线",
                "plan_total_length": 1699.0,
                "pressure_pipe_structure_type": "有压管道",
            },
        ],
    }

    result = cad_tools.SectionSummaryDialog._read_pressurized_rows(
        dlg,
        [(dialog_row, _DummyCombo("HDPE管"), _DummyLineEdit("400"))],
        "有压管道",
    )

    assert [row["identity"] for row in result] == ["flow1-row114", "flow1-row115"]
    assert all(row["pipe_material"] == "HDPE管" for row in result)
    assert all(row["DN_mm"] == 400 for row in result)
    assert all(row["plan_total_length"] == 1699.0 for row in result)
    assert result[0]["route_key"] == "route-main"
    assert result[1]["route_display_name"] == "主线"


def test_read_pressurized_rows_named_special_group_only_updates_itself():
    dlg = _dialog_shell(
        _current_pressure_pipe_material_value=lambda combo: combo.currentText(),
    )
    ordinary_row = {
        "name": "第一流量段",
        "flow_section": 1,
        "display_name": "第一流量段",
        "structure_kind": "pressure_pipe",
        "dialog_row_kind": "flow_section_pressure_pipe",
        "dialog_target_identities": ["flow1-row114", "flow1-row115"],
        "dialog_target_rows": [
            {
                "name": "未命名有压管道",
                "flow_section": 1,
                "display_name": "流量段1 第114行有压管道",
                "structure_kind": "pressure_pipe",
                "identity": "flow1-row114",
                "pipe_material": "HDPE管",
                "DN_mm": 400,
                "pressure_pipe_structure_type": "有压管道",
            },
            {
                "name": "未命名有压管道",
                "flow_section": 1,
                "display_name": "流量段1 第115行有压管道",
                "structure_kind": "pressure_pipe",
                "identity": "flow1-row115",
                "pipe_material": "HDPE管",
                "DN_mm": 400,
                "pressure_pipe_structure_type": "有压管道",
            },
        ],
    }
    special_row = {
        "name": "磨盘寨",
        "flow_section": 1,
        "display_name": "磨盘寨",
        "structure_kind": "pressure_pipe",
        "dialog_row_kind": "named_pressure_like_group",
        "dialog_target_identities": ["flow1-mpz"],
        "dialog_target_rows": [
            {
                "name": "磨盘寨",
                "flow_section": 1,
                "display_name": "磨盘寨",
                "structure_kind": "pressure_pipe",
                "identity": "flow1-mpz",
                "pipe_material": "钢管",
                "DN_mm": 500,
                "pressure_pipe_structure_type": "定向钻",
            }
        ],
    }

    ordinary_result = cad_tools.SectionSummaryDialog._read_pressurized_rows(
        dlg,
        [(ordinary_row, _DummyCombo("HDPE管"), _DummyLineEdit("400"))],
        "有压管道",
    )
    special_result = cad_tools.SectionSummaryDialog._read_pressurized_rows(
        dlg,
        [(special_row, _DummyCombo("钢管"), _DummyLineEdit("500"))],
        "有压管道",
    )

    assert [row["identity"] for row in ordinary_result] == ["flow1-row114", "flow1-row115"]
    assert [row["identity"] for row in special_result] == ["flow1-mpz"]
    assert special_result[0]["pipe_material"] == "钢管"
    assert special_result[0]["DN_mm"] == 500


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


def test_prepare_pressure_pipe_export_rows_uses_identity_results_for_unnamed_segments():
    rows = [
        {
            "name": "",
            "flow_section": 2,
            "display_name": "未命名有压管道-第二流量段",
            "pipe_material": "HDPE管",
            "DN_mm": 400,
            "structure_kind": "pressure_pipe",
            "identity": "flow2-row6",
            "Q": 0.1,
        }
    ]
    panel = SimpleNamespace(
        get_pressure_pipe_export_results=lambda export_rows=None: {
            "flow2-row6": {"pipe_velocity": 0.7954, "total_length": 1699.0, "source": "table3"}
        }
    )

    prepared = cad_tools._prepare_pressure_pipe_export_rows(rows, panel=panel, calc_contexts={})
    computed = summary_mod.compute_pressure_pipe(prepared)
    _, _, _, table_rows, _ = summary_mod._dxf_build_pressure_pipe(computed)

    assert prepared[0]["V"] == 0.7954
    assert prepared[0]["total_length"] == 1699.0
    assert table_rows[0][3] == 1.699
    assert table_rows[0][6] == 0.7954


def test_prepare_pressure_pipe_export_rows_prefers_total_length_from_panel_results():
    rows = [
        {
            "name": "牛马道",
            "flow_section": 3,
            "display_name": "牛马道-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 1600,
            "structure_kind": "pressure_pipe",
            "plan_total_length": 1480.0,
        }
    ]
    panel = SimpleNamespace(
        get_pressure_pipe_export_results=lambda export_rows=None: {
            "3::牛马道": {"total_length": 1520.0, "source": "table3"}
        }
    )

    prepared = cad_tools._prepare_pressure_pipe_export_rows(rows, panel=panel, calc_contexts={})

    assert prepared[0]["total_length"] == 1520.0


def test_prepare_pressure_pipe_export_rows_falls_back_to_plan_total_length():
    rows = [
        {
            "name": "牛马道",
            "flow_section": 3,
            "display_name": "牛马道-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 1600,
            "structure_kind": "pressure_pipe",
            "plan_total_length": 1480.0,
        }
    ]
    panel = SimpleNamespace(get_pressure_pipe_export_results=lambda export_rows=None: {})

    prepared = cad_tools._prepare_pressure_pipe_export_rows(rows, panel=panel, calc_contexts={})

    assert prepared[0]["total_length"] == 1480.0


def test_prepare_pressure_pipe_export_rows_uses_panel_velocity_for_cached_rows():
    rows = [
        {
            "name": "牛马道",
            "flow_section": 3,
            "display_name": "牛马道-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 1600,
            "structure_kind": "pressure_pipe",
            "Q": 3.0,
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


def test_prepare_pressure_pipe_export_rows_prefers_row_identity_for_unnamed_cached_rows():
    rows = [
        {
            "name": "",
            "flow_section": 2,
            "identity": "flow2-row4",
            "display_name": "未命名有压管道-第二流量段",
            "pipe_material": "HDPE管",
            "DN_mm": 400,
            "structure_kind": "pressure_pipe",
            "Q": 0.1,
        }
    ]
    panel = SimpleNamespace(
        get_pressure_pipe_export_results=lambda export_rows=None: {
            "flow2-row4": {"pipe_velocity": 0.796, "total_length": 1699.0, "source": "table3"}
        }
    )

    prepared = cad_tools._prepare_pressure_pipe_export_rows(rows, panel=panel, calc_contexts={})
    computed = summary_mod.compute_pressure_pipe(prepared)
    _, _, _, table_rows, _ = summary_mod._dxf_build_pressure_pipe(computed)

    assert prepared[0]["V"] == 0.796
    assert prepared[0]["total_length"] == 1699.0
    assert table_rows[0][3] == 1.699
    assert table_rows[0][6] == 0.796


def test_prepare_pressure_pipe_export_rows_backfills_velocity_from_q_and_dn_when_export_result_missing():
    rows = [
        {
            "name": "牛马道",
            "flow_section": 3,
            "display_name": "牛马道-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 1600,
            "structure_kind": "pressure_pipe",
            "Q": 3.0,
        }
    ]
    panel = SimpleNamespace(get_pressure_pipe_export_results=lambda export_rows=None: {})

    prepared = cad_tools._prepare_pressure_pipe_export_rows(rows, panel=panel, calc_contexts={})
    computed = summary_mod.compute_pressure_pipe(prepared)
    _, _, _, table_rows, _ = summary_mod._dxf_build_pressure_pipe(computed)

    assert prepared[0]["V"] == 1.4921
    assert computed[0]["V"] == 1.4921
    assert table_rows[0][6] == 1.4921


def test_prepare_pressure_pipe_export_rows_preserves_existing_velocity_over_q_dn_backfill():
    rows = [
        {
            "name": "牛马道",
            "flow_section": 3,
            "display_name": "牛马道-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 1600,
            "structure_kind": "pressure_pipe",
            "Q": 3.0,
            "V": 1.377,
        }
    ]
    panel = SimpleNamespace(get_pressure_pipe_export_results=lambda export_rows=None: {})

    prepared = cad_tools._prepare_pressure_pipe_export_rows(rows, panel=panel, calc_contexts={})

    assert prepared[0]["V"] == 1.377


def test_section_summary_dialog_read_pressurized_rows_preserves_pressure_pipe_identity_metadata():
    dlg = _dialog_shell(
        _current_pressure_pipe_material_value=lambda combo: combo.currentText(),
    )
    source_row = {
        "name": "",
        "flow_section": 2,
        "display_name": "未命名有压管道-第二流量段",
        "pipe_material": "旧材质",
        "DN_mm": 350,
        "structure_kind": "pressure_pipe",
        "identity": "flow2-row4",
        "storage_key": "pressure_pipe_row_identity",
        "route_key": "route-main",
        "route_display_name": "干线A",
        "V": 0.72,
        "total_length": 1688.0,
        "plan_total_length": 1680.0,
        "total_head_loss": 0.42,
    }
    rows = [
        (
            source_row,
            SimpleNamespace(currentText=lambda: "HDPE管"),
            SimpleNamespace(text=lambda: "400"),
        )
    ]

    result = cad_tools.SectionSummaryDialog._read_pressurized_rows(dlg, rows, "有压管道")

    assert result[0]["display_name"] == "未命名有压管道-第二流量段"
    assert result[0]["pipe_material"] == "HDPE管"
    assert result[0]["DN_mm"] == 400
    assert result[0]["identity"] == "flow2-row4"
    assert result[0]["storage_key"] == "pressure_pipe_row_identity"
    assert result[0]["route_key"] == "route-main"
    assert result[0]["route_display_name"] == "干线A"
    assert result[0]["V"] == 0.72
    assert result[0]["total_length"] == 1688.0
    assert result[0]["plan_total_length"] == 1680.0
    assert result[0]["total_head_loss"] == 0.42


def test_prepare_pressure_pipe_export_rows_warns_when_velocity_cannot_be_backfilled(monkeypatch):
    rows = [
        {
            "name": "缺参管道",
            "flow_section": 3,
            "display_name": "缺参管道-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": None,
            "structure_kind": "pressure_pipe",
            "Q": 3.0,
        }
    ]
    panel = SimpleNamespace(get_pressure_pipe_export_results=lambda export_rows=None: {})
    notices = []

    monkeypatch.setattr(
        cad_tools,
        "fluent_info",
        lambda parent, title, message: notices.append((parent, title, message)),
    )

    prepared = cad_tools._prepare_pressure_pipe_export_rows(rows, panel=panel, calc_contexts={})
    cad_tools.SectionSummaryDialog._warn_pressure_pipe_missing_velocity(_dialog_shell(), prepared)
    computed = summary_mod.compute_pressure_pipe(prepared)
    _, _, _, table_rows, _ = summary_mod._dxf_build_pressure_pipe(computed)

    assert "V" not in prepared[0]
    assert table_rows[0][6] == "-"
    assert notices
    assert notices[0][1] == "提示"
    assert "缺参管道" in notices[0][2]
    assert "Q/DN" in notices[0][2]


def test_merge_pressure_pipe_export_rows_by_flow_section_collapses_rows_and_attaches_summary():
    rows = [
        {
            "name": "牛马道主线",
            "flow_section": 3,
            "display_name": "牛马道主线-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 1600,
            "structure_kind": "pressure_pipe",
            "Q": 3.0,
            "Q_inc": 3.75,
            "V": 1.49,
            "total_length": 1520.0,
            "total_head_loss": 0.5627,
            "friction_params": "223200 / 1.852 / 4.87",
        },
        {
            "name": "牛马道支线",
            "flow_section": 3,
            "display_name": "牛马道支线-第三流量段",
            "pipe_material": "球墨铸铁管",
            "DN_mm": 1600,
            "structure_kind": "pressure_pipe",
            "Q": 3.0,
        },
        {
            "name": "四段管道",
            "flow_section": 4,
            "display_name": "四段管道-第四流量段",
            "pipe_material": "钢管",
            "DN_mm": 1400,
            "structure_kind": "pressure_pipe",
            "Q": 2.2,
            "Q_inc": 2.75,
            "V": 1.31,
            "total_length": 980.0,
        },
    ]
    panel = SimpleNamespace(
        get_pressure_pipe_characteristic_export_summary=lambda export_rows=None: {
            "3": {
                "total_length": 1699.0,
                "start_water_level": 512.3,
                "end_water_level": 509.7,
                "tunnel_count": 2,
                "tunnel_length": 1200.0,
                "directional_drill_count": 1,
                "directional_drill_length": 200.0,
                "jacking_count": 0,
                "jacking_length": 0.0,
            },
            "4": {
                "start_water_level": 512.3,
                "end_water_level": 509.7,
                "tunnel_count": 0,
                "tunnel_length": 0.0,
                "directional_drill_count": 0,
                "directional_drill_length": 0.0,
                "jacking_count": 0,
                "jacking_length": 0.0,
            },
        }
    )

    merged = cad_tools._merge_pressure_pipe_export_rows_by_flow_section(rows, panel=panel)

    assert [row["flow_section"] for row in merged] == [3, 4]
    assert [row["name"] for row in merged] == ["第三流量段", "第四流量段"]
    assert merged[0]["total_length"] == 1699.0
    assert merged[0]["start_water_level"] == 512.3
    assert merged[0]["end_water_level"] == 509.7
    assert merged[0]["tunnel_count"] == 2
    assert merged[0]["directional_drill_count"] == 1
    assert merged[0]["jacking_count"] == 0
    assert merged[0]["show_building_characteristics"] is True
    assert merged[1]["show_building_characteristics"] is True


def test_merge_pressure_pipe_export_rows_by_flow_section_prefers_segment_ranges_for_total_length():
    rows = [
        {
            "name": "第一段普通有压管道",
            "flow_section": 1,
            "display_name": "第一段普通有压管道-第一流量段",
            "pipe_material": "HDPE管",
            "DN_mm": 400,
            "structure_kind": "pressure_pipe",
            "Q": 0.1,
            "segment_start_mc": 0.0,
            "segment_end_mc": 400.0,
        },
        {
            "name": "第一段定向钻",
            "flow_section": 1,
            "display_name": "第一段定向钻-第一流量段",
            "pipe_material": "钢管",
            "DN_mm": 400,
            "structure_kind": "pressure_pipe",
            "Q": 0.1,
            "segment_start_mc": 400.0,
            "segment_end_mc": 1200.0,
        },
        {
            "name": "第二段普通有压管道",
            "flow_section": 1,
            "display_name": "第二段普通有压管道-第一流量段",
            "pipe_material": "HDPE管",
            "DN_mm": 400,
            "structure_kind": "pressure_pipe",
            "Q": 0.1,
            "segment_start_mc": 1200.0,
            "segment_end_mc": 1699.0,
        },
    ]
    panel = SimpleNamespace(
        get_pressure_pipe_characteristic_export_summary=lambda export_rows=None: {
            "1": {
                "total_length": 800.0,
                "start_water_level": 397.16,
                "end_water_level": 384.203,
                "tunnel_count": 0,
                "tunnel_length": 0.0,
                "directional_drill_count": 2,
                "directional_drill_length": 0.8,
                "jacking_count": 0,
                "jacking_length": 0.0,
            }
        }
    )

    merged = cad_tools._merge_pressure_pipe_export_rows_by_flow_section(rows, panel=panel)

    assert len(merged) == 1
    assert merged[0]["total_length"] == 1699.0
    assert merged[0]["directional_drill_count"] == 2


def test_panel_pressure_pipe_characteristic_summary_merges_tunnel_subtypes_and_accumulates_lengths():
    dummy_panel = SimpleNamespace(
        calculated_nodes=[
            SimpleNamespace(
                flow_section="3",
                station_MC=0.0,
                water_level=512.3,
                structure_type=SimpleNamespace(value="隧洞-圆形"),
                is_transition=False,
                is_auto_inserted_channel=False,
                is_pressure_pipe=False,
            ),
            SimpleNamespace(
                flow_section="3",
                station_MC=400.0,
                water_level=511.8,
                structure_type=SimpleNamespace(value="隧洞-马蹄形Ⅰ型"),
                is_transition=False,
                is_auto_inserted_channel=False,
                is_pressure_pipe=False,
            ),
            SimpleNamespace(
                flow_section="3",
                station_MC=650.0,
                water_level=511.0,
                structure_type=SimpleNamespace(value="定向钻"),
                is_transition=False,
                is_auto_inserted_channel=False,
                is_pressure_pipe=False,
            ),
            SimpleNamespace(
                flow_section="3",
                station_MC=850.0,
                water_level=510.2,
                structure_type=SimpleNamespace(value="顶管"),
                is_transition=False,
                is_auto_inserted_channel=False,
                is_pressure_pipe=False,
            ),
            SimpleNamespace(
                flow_section="3",
                station_MC=1000.0,
                water_level=509.7,
                structure_type=SimpleNamespace(value="有压管道"),
                is_transition=False,
                is_auto_inserted_channel=False,
                is_pressure_pipe=True,
            ),
        ],
        _build_settings=lambda: SimpleNamespace(),
    )
    for name in (
        "_collect_pressure_pipe_export_targets",
        "_build_pressure_pipe_characteristic_export_summary_from_nodes",
        "_get_pressure_pipe_summary_source_nodes",
        "_get_pressure_pipe_summary_waterline",
    ):
        setattr(
            dummy_panel,
            name,
            getattr(panel_mod.WaterProfilePanel, name).__get__(dummy_panel, type(dummy_panel)),
        )
    dummy_panel._normalize_pressure_pipe_summary_flow_section = (
        panel_mod.WaterProfilePanel._normalize_pressure_pipe_summary_flow_section
    )
    dummy_panel._normalize_pressure_pipe_export_number = (
        panel_mod.WaterProfilePanel._normalize_pressure_pipe_export_number
    )
    dummy_panel._get_pressure_pipe_summary_structure_type = (
        panel_mod.WaterProfilePanel._get_pressure_pipe_summary_structure_type
    )
    dummy_panel._make_pressure_pipe_export_target = (
        panel_mod.WaterProfilePanel._make_pressure_pipe_export_target
    )
    dummy_panel._classify_pressure_pipe_summary_bucket = (
        lambda node: panel_mod.WaterProfilePanel._classify_pressure_pipe_summary_bucket(node)
    )

    summary = panel_mod.WaterProfilePanel.get_pressure_pipe_characteristic_export_summary(
        dummy_panel,
        rows=[{"name": "第三流量段", "flow_section": 3}],
    )

    assert summary["3"]["total_length"] == 1000.0
    assert summary["3"]["start_water_level"] == 512.3
    assert summary["3"]["end_water_level"] == 509.7
    assert summary["3"]["tunnel_count"] == 1
    assert summary["3"]["tunnel_length"] == 650.0
    assert summary["3"]["directional_drill_count"] == 1
    assert summary["3"]["directional_drill_length"] == 200.0
    assert summary["3"]["jacking_count"] == 1
    assert summary["3"]["jacking_length"] == 150.0


def test_panel_pressure_pipe_characteristic_summary_includes_plain_pressure_pipe_segments_in_total_length():
    dummy_panel = SimpleNamespace(
        calculated_nodes=[
            SimpleNamespace(
                flow_section="1",
                station_MC=0.0,
                water_level=397.16,
                structure_type=SimpleNamespace(value="有压管道"),
                is_transition=False,
                is_auto_inserted_channel=False,
                is_pressure_pipe=True,
            ),
            SimpleNamespace(
                flow_section="1",
                station_MC=200.0,
                water_level=394.0,
                structure_type=SimpleNamespace(value="定向钻"),
                is_transition=False,
                is_auto_inserted_channel=False,
                is_pressure_pipe=False,
            ),
            SimpleNamespace(
                flow_section="1",
                station_MC=500.0,
                water_level=391.2,
                structure_type=SimpleNamespace(value="有压管道"),
                is_transition=False,
                is_auto_inserted_channel=False,
                is_pressure_pipe=True,
            ),
            SimpleNamespace(
                flow_section="1",
                station_MC=700.0,
                water_level=388.9,
                structure_type=SimpleNamespace(value="顶管"),
                is_transition=False,
                is_auto_inserted_channel=False,
                is_pressure_pipe=False,
            ),
            SimpleNamespace(
                flow_section="1",
                station_MC=1000.0,
                water_level=384.203,
                structure_type=SimpleNamespace(value="有压管道"),
                is_transition=False,
                is_auto_inserted_channel=False,
                is_pressure_pipe=True,
            ),
        ],
        _build_settings=lambda: SimpleNamespace(),
    )
    for name in (
        "_collect_pressure_pipe_export_targets",
        "_build_pressure_pipe_characteristic_export_summary_from_nodes",
        "_get_pressure_pipe_summary_source_nodes",
        "_get_pressure_pipe_summary_waterline",
    ):
        setattr(
            dummy_panel,
            name,
            getattr(panel_mod.WaterProfilePanel, name).__get__(dummy_panel, type(dummy_panel)),
        )
    dummy_panel._normalize_pressure_pipe_summary_flow_section = (
        panel_mod.WaterProfilePanel._normalize_pressure_pipe_summary_flow_section
    )
    dummy_panel._normalize_pressure_pipe_export_number = (
        panel_mod.WaterProfilePanel._normalize_pressure_pipe_export_number
    )
    dummy_panel._get_pressure_pipe_summary_structure_type = (
        panel_mod.WaterProfilePanel._get_pressure_pipe_summary_structure_type
    )
    dummy_panel._make_pressure_pipe_export_target = (
        panel_mod.WaterProfilePanel._make_pressure_pipe_export_target
    )
    dummy_panel._classify_pressure_pipe_summary_bucket = (
        lambda node: panel_mod.WaterProfilePanel._classify_pressure_pipe_summary_bucket(node)
    )

    summary = panel_mod.WaterProfilePanel.get_pressure_pipe_characteristic_export_summary(
        dummy_panel,
        rows=[{"name": "第一流量段", "flow_section": 1}],
    )

    assert summary["1"]["total_length"] == 1000.0
    assert summary["1"]["start_water_level"] == 397.16
    assert summary["1"]["end_water_level"] == 384.203
    assert summary["1"]["directional_drill_count"] == 1
    assert summary["1"]["directional_drill_length"] == 300.0
    assert summary["1"]["jacking_count"] == 1
    assert summary["1"]["jacking_length"] == 300.0


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
            "3::牛马道": {
                "total_head_loss": 0.5627,
                "total_length": 1520.0,
                "pipe_velocity": 1.49,
                "source": "table3",
            }
        },
        get_pressure_pipe_characteristic_export_summary=lambda export_rows=None: {
            "3": {
                "start_water_level": 512.3,
                "end_water_level": 509.7,
                "tunnel_count": 2,
                "tunnel_length": 1200.0,
                "directional_drill_count": 0,
                "directional_drill_length": 0.0,
                "jacking_count": 1,
                "jacking_length": 300.0,
            }
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

    pressure_rows = captured["压力管道特性表"]
    assert pressure_rows[0][0] == "第三流量段"
    assert pressure_rows[0][3] == 1.52
    assert pressure_rows[0][6] == 1.49
    assert pressure_rows[0][7] == 512.3
    assert pressure_rows[0][8] == 509.7
    assert pressure_rows[0][-6:] == [2, 1.2, "-", "-", 1, 0.3]


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
    assert summary_mod.normalize_pressure_pipe_material_key("PE管") == "HDPE管"
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


def test_write_pressure_pipe_uses_characteristics_headers_and_hidden_metrics():
    openpyxl, styles, gcl = summary_mod._get_openpyxl()
    wb = openpyxl.Workbook()
    ws = wb.active

    ncols = summary_mod._write_pressure_pipe(
        ws,
        summary_mod.compute_pressure_pipe([
            {
                "name": "第三流量段",
                "Q": 3.0,
                "DN_mm": 1600,
                "pipe_material": "球墨铸铁管",
                "V": 1.438,
                "total_length": 1520.0,
                "total_head_loss": 0.5627,
                "start_water_level": 512.3,
                "end_water_level": 509.7,
                "tunnel_count": 2,
                "tunnel_length": 1200.0,
                "directional_drill_count": 0,
                "directional_drill_length": 0.0,
                "jacking_count": 1,
                "jacking_length": 300.0,
                "show_building_characteristics": True,
            }
        ]),
        styles,
        gcl,
    )

    assert ncols == 15
    assert ws.cell(1, 1).value == "压力管道特性表"
    assert ws.cell(2, 8).value == "设计压力线"
    assert ws.cell(3, 8).value == "渠首水位"
    assert ws.cell(4, 8).value == "m"
    assert ws.cell(2, 10).value == "建筑物特性"
    assert ws.cell(3, 10).value == "隧洞"
    assert ws.cell(4, 10).value == "座数"
    assert ws.cell(4, 11).value == "长度（km）"
    assert [ws.cell(5, c).value for c in range(1, 16)] == [
        "第三流量段", 3.0, 3.75, 1.52, "球墨铸铁管", 1.6, 1.438,
        512.3, 509.7, 2, 1.2, "-", "-", 1, 0.3,
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


def test_warn_pressure_pipe_missing_total_head_loss_is_suppressed(monkeypatch):
    dlg = _dialog_shell(
        _compute_pressure_pipe=summary_mod.compute_pressure_pipe,
    )
    calls = []

    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: calls.append((args, kwargs)))

    cad_tools.SectionSummaryDialog._warn_pressure_pipe_missing_total_head_loss(
        dlg,
        [{"name": "缺损失-第一流量段", "Q": 1.0, "DN_mm": 1000, "pipe_material": "球墨铸铁管"}],
    )

    assert calls == []


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

