# -*- coding: utf-8 -*-
"""合并导出 DXF（纵断面 + 断面汇总 + IP表）行为单元测试。"""

from pathlib import Path
import importlib
import importlib.util
import sys
from types import SimpleNamespace


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_combined_dxf_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


def _load_panel_class():
    helper_path = Path(__file__).with_name("test_pressure_pipe_export_longitudinal_nodes_unit.py")
    spec = importlib.util.spec_from_file_location("panel_longitudinal_nodes_helper_mod", helper_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._load_panel_class()


class _TextStub:
    def __init__(self, value):
        self._value = value

    def text(self):
        return self._value


class _ComboStub:
    def __init__(self, value):
        self._value = value

    def currentText(self):
        return self._value


class _Settings:
    design_flows = [0.65, 0.58]

    def get_station_prefix(self):
        return ""


class _ProfileNode(SimpleNamespace):
    def get_structure_type_str(self):
        struct = getattr(self, "structure_type", None)
        if struct is None:
            return ""
        if hasattr(struct, "value"):
            return struct.value
        return str(struct)


class _AcceptedTextDialog:
    def __init__(self, *args, **kwargs):
        self.result = {}

    def exec(self):
        return cad_tools.QDialog.Accepted


class _FakeLayers(dict):
    def new(self, name, dxfattribs=None):
        self[name] = dxfattribs or {}


class _FakeDoc:
    def __init__(self):
        self.layers = _FakeLayers({"0": {}})
        self.saved_path = None
        self._msp = SimpleNamespace()

    def modelspace(self):
        return self._msp

    def saveas(self, path):
        self.saved_path = path


class _RecordingTextEntity:
    def __init__(self, msp, text, dxfattribs=None):
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


class _RecordingMSP:
    def __init__(self):
        self.line_records = []
        self.text_records = []
        self.polyline_records = []

    def add_line(self, start, end, dxfattribs=None, **_kwargs):
        self.line_records.append(
            {
                "start": (float(start[0]), float(start[1])),
                "end": (float(end[0]), float(end[1])),
                "dxfattribs": dict(dxfattribs or {}),
            }
        )
        return None

    def add_lwpolyline(self, points, dxfattribs=None, **_kwargs):
        self.polyline_records.append(
            {
                "points": [(float(x), float(y)) for x, y in points],
                "dxfattribs": dict(dxfattribs or {}),
            }
        )
        return None

    def add_text(self, text, dxfattribs=None):
        return _RecordingTextEntity(self, text, dxfattribs)


class _RecordingDoc(_FakeDoc):
    def __init__(self):
        super().__init__()
        self._msp = _RecordingMSP()


def _build_panel(*, name="N1", structure_type="明渠-矩形"):
    node = SimpleNamespace(
        bottom_elevation=408.5,
        top_elevation=409.2,
        water_level=408.9,
        structure_type=SimpleNamespace(value=structure_type),
        is_transition=False,
        is_auto_inserted_channel=False,
        name=name,
    )
    panel = SimpleNamespace(
        calculated_nodes=[node],
        _text_export_settings={},
        _custom_pressurized_pipe_params={},
        channel_name_edit=_TextStub("测试渠"),
        channel_level_combo=_ComboStub("支渠"),
    )
    panel.window = lambda: panel
    panel._build_settings = lambda: _Settings()
    return panel


def _patch_common(monkeypatch):
    docs = {}

    def _fake_new(_version):
        doc = _FakeDoc()
        docs["doc"] = doc
        return doc

    monkeypatch.setitem(sys.modules, "ezdxf", SimpleNamespace(new=_fake_new))
    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _AcceptedTextDialog)
    monkeypatch.setattr(cad_tools, "_setup_dxf_style", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_ensure_profile_layers", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", lambda *_a, **_k: (240.0, 120.0))
    monkeypatch.setattr(
        cad_tools.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_a, **_k: ("C:/tmp/combined_test.dxf", "DXF")),
    )
    return docs


def _make_profile_node(
    *,
    mc,
    structure,
    name,
    bottom,
    top,
    water,
    ip_no=1,
    in_out="",
    is_transition=False,
    is_auto_inserted_channel=False,
    flow_section="1",
    row_identity="",
):
    return _ProfileNode(
        station_MC=float(mc),
        station_BC=float(mc),
        station_EC=float(mc),
        turn_angle=0.0,
        structure_type=SimpleNamespace(value=structure),
        name=name,
        flow_section=flow_section,
        in_out=SimpleNamespace(value=in_out) if in_out else None,
        is_transition=bool(is_transition),
        is_auto_inserted_channel=bool(is_auto_inserted_channel),
        is_inverted_siphon=False,
        is_pressure_pipe=structure in {"有压管道", "定向钻", "顶管"},
        bottom_elevation=float(bottom),
        top_elevation=float(top),
        water_level=float(water),
        ip_number=int(ip_no),
        slope_i=1 / 3000,
        pressure_pipe_row_identity=str(row_identity or ""),
    )


def _polyline_has_x_backtracking(points, tol=1e-9):
    last_x = None
    for x_value, _y_value in points:
        if last_x is not None and float(x_value) < float(last_x) - tol:
            return True
        last_x = float(x_value)
    return False


def _has_line(records, start, end, layer=None, tol=1e-6):
    for rec in records:
        if layer is not None and rec["dxfattribs"].get("layer") != layer:
            continue
        if (
            abs(rec["start"][0] - start[0]) <= tol
            and abs(rec["start"][1] - start[1]) <= tol
            and abs(rec["end"][0] - end[0]) <= tol
            and abs(rec["end"][1] - end[1]) <= tol
        ):
            return True
    return False


def _make_strict_mixed_tail_nodes():
    return [
        _make_profile_node(
            ip_no=1,
            mc=0.0,
            structure="明渠-矩形",
            name="前段明渠",
            bottom=410.0,
            top=411.0,
            water=410.5,
        ),
        _make_profile_node(
            ip_no=2,
            mc=40.0,
            structure="隧洞-圆拱直墙型",
            name="前段隧洞",
            bottom=409.6,
            top=0.0,
            water=0.0,
            row_identity="flow1-row2",
        ),
        _make_profile_node(
            ip_no=3,
            mc=80.0,
            structure="有压管道",
            name="压力段1",
            bottom=409.0,
            top=0.0,
            water=0.0,
            in_out="进",
            row_identity="flow1-row3",
        ),
        _make_profile_node(
            ip_no=4,
            mc=120.0,
            structure="隧洞-圆拱直墙型",
            name="交错隧洞",
            bottom=408.5,
            top=0.0,
            water=0.0,
            row_identity="flow1-row4",
        ),
        _make_profile_node(
            ip_no=5,
            mc=160.0,
            structure="顶管",
            name="压力段2",
            bottom=408.0,
            top=0.0,
            water=0.0,
            in_out="出",
            row_identity="flow1-row5",
        ),
    ]


def test_combined_dxf_stops_when_summary_generation_raises(monkeypatch):
    docs = _patch_common(monkeypatch)
    panel = _build_panel()
    errors = []

    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        cad_tools,
        "_draw_section_summary_on_msp",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("summary boom")),
    )

    cad_tools.export_combined_dxf(panel)

    assert errors, "断面汇总失败时应提示错误"
    assert "断面汇总表生成失败" in errors[-1][2]
    assert docs["doc"].saved_path is None


def test_combined_dxf_stops_when_summary_has_no_tables(monkeypatch):
    docs = _patch_common(monkeypatch)
    panel = _build_panel()
    errors = []

    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (0.0, 0.0, 0))

    cad_tools.export_combined_dxf(panel)

    assert errors, "断面汇总无数据时应提示错误"
    assert "断面汇总表无可导出内容" in errors[-1][2]
    assert docs["doc"].saved_path is None


def test_combined_dxf_saves_when_all_sections_succeed(monkeypatch):
    docs = _patch_common(monkeypatch)
    panel = _build_panel()
    errors = []
    questions = []

    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: questions.append(args) or False)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 2))
    monkeypatch.setattr(
        cad_tools,
        "_compute_ip_preview_data",
        lambda *_a, **_k: ([["IP1"], ["IP2"], ["IP3"]], []),
    )
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)

    cad_tools.export_combined_dxf(panel)

    assert not errors
    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert questions, "成功导出后应弹出打开文件确认"
    assert "断面汇总表: 2" in questions[-1][2]


def test_export_combined_dxf_opens_text_dialog_in_xxpipe_mode(monkeypatch):
    panel = _build_panel(structure_type="有压管道")
    captured = {}

    class _Dialog:
        def __init__(self, *args, **kwargs):
            captured["mode"] = kwargs.get("mode")
            self.result = None

        def exec(self):
            return cad_tools.QDialog.Rejected

    monkeypatch.setattr(cad_tools, "MODELS_AVAILABLE", True)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda obj: obj)
    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _Dialog)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *_a, **_k: None)

    cad_tools.export_combined_dxf(panel)

    assert captured["mode"] == "xxpipe"


def test_combined_dxf_warns_but_saves_when_open_channel_name_missing(monkeypatch):
    docs = _patch_common(monkeypatch)
    panel = _build_panel(name="")
    errors = []
    infos = []
    questions = []

    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: infos.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: questions.append(args) or False)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(
        cad_tools,
        "_compute_ip_preview_data",
        lambda *_a, **_k: ([["IP1"]], []),
    )
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)

    cad_tools.export_combined_dxf(panel)

    assert not errors
    assert infos, "明渠名称为空时应给出非阻断提示"
    assert "部分建筑物名称为空" in infos[-1][2]
    assert "第1行（明渠-矩形）" in infos[-1][2]
    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert questions, "成功导出后仍应弹出打开文件确认"


def test_combined_dxf_warns_with_generic_message_when_pressure_pipe_name_missing(monkeypatch):
    docs = _patch_common(monkeypatch)
    panel = _build_panel(name="", structure_type="有压管道")
    errors = []
    infos = []
    questions = []

    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: infos.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: questions.append(args) or False)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(
        cad_tools,
        "_compute_ip_preview_data",
        lambda *_a, **_k: ([["IP1"]], []),
    )
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)

    cad_tools.export_combined_dxf(panel)

    assert not errors
    assert infos, "有压管道名称为空时应给出非阻断提示"
    assert "部分建筑物名称为空" in infos[-1][2]
    assert "明渠名称为空" not in infos[-1][2]
    assert "第1行（有压管道）" in infos[-1][2]
    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert questions, "成功导出后仍应弹出打开文件确认"


def test_draw_section_summary_on_msp_splits_mixed_horseshoe_tables(monkeypatch):
    actual_summary = importlib.import_module("calc_渠系计算算法内核.生成断面汇总表")
    captured_titles = []

    def _fake_draw_table(msp, x0, y0, title, headers, col_widths, rows, merge_groups=None, layer="0"):
        _ = (msp, x0, y0, headers, col_widths, rows, merge_groups, layer)
        captured_titles.append(title)
        return 100.0

    monkeypatch.setattr(actual_summary, "_dxf_draw_table", _fake_draw_table)

    panel = SimpleNamespace(
        _custom_struct_thickness=None,
        _custom_rock_lining=None,
        _custom_tunnel_unified={},
    )
    nodes = [
        SimpleNamespace(
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            structure_type=SimpleNamespace(value="隧洞-马蹄形Ⅰ型"),
            name="马蹄Ⅰ",
            flow_section="1",
            flow=2.0,
            roughness=0.014,
            slope_i=1 / 1500,
            section_params={"R": 1.8, "horseshoe_section_type": 1},
            water_depth=1.25,
            velocity=1.48,
            rock_class="III",
        ),
        SimpleNamespace(
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            structure_type=SimpleNamespace(value="隧洞-马蹄形Ⅱ型"),
            name="马蹄Ⅱ",
            flow_section="2",
            flow=1.5,
            roughness=0.014,
            slope_i=1 / 1800,
            section_params={"R": 2.2, "horseshoe_section_type": 2},
            water_depth=1.35,
            velocity=1.32,
            rock_class="IV",
        ),
    ]

    _, _, drawn_count = cad_tools._draw_section_summary_on_msp(
        panel=panel,
        msp=object(),
        nodes=nodes,
        proj_settings=None,
        pressurized_params={"siphon": [], "pressure_pipe": []},
        below_y=0.0,
        summary_layer="SUMMARY",
    )

    assert drawn_count == 2
    assert any("马蹄形标准Ⅰ型隧洞断面尺寸及水力要素表" == title for title in captured_titles)
    assert any("马蹄形标准Ⅱ型隧洞断面尺寸及水力要素表" == title for title in captured_titles)


def test_draw_section_summary_on_msp_keeps_open_channel_without_increase_columns(monkeypatch):
    actual_summary = importlib.import_module("calc_渠系计算算法内核.生成断面汇总表")
    captured_tables = []

    def _fake_draw_table(msp, x0, y0, title, headers, col_widths, rows, merge_groups=None, layer="0"):
        _ = (msp, x0, y0, col_widths, merge_groups, layer)
        captured_tables.append({
            "title": title,
            "headers": headers,
            "rows": rows,
        })
        return 120.0

    monkeypatch.setattr(actual_summary, "_dxf_draw_table", _fake_draw_table)

    panel = SimpleNamespace(
        _custom_struct_thickness=None,
        _custom_rock_lining=None,
        _custom_tunnel_unified={},
    )
    nodes = [
        SimpleNamespace(
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            structure_type=SimpleNamespace(value="明渠-矩形"),
            name="甘家沟充水渠",
            flow_section="1",
            flow=1.0,
            roughness=0.014,
            slope_i=1 / 2000,
            section_params={"B": 1.5, "use_increase": False},
            water_depth=0.789,
            velocity=0.845,
            structure_height=1.19,
        ),
    ]

    _, _, drawn_count = cad_tools._draw_section_summary_on_msp(
        panel=panel,
        msp=object(),
        nodes=nodes,
        proj_settings=None,
        pressurized_params={"siphon": [], "pressure_pipe": []},
        below_y=0.0,
        summary_layer="SUMMARY",
    )

    assert drawn_count == 1
    assert len(captured_tables) == 1
    assert captured_tables[0]["title"] == "矩形明渠断面尺寸及水力要素表"
    header_names = [name for name, _unit in captured_tables[0]["headers"]]
    assert "加大流量" not in header_names
    assert "加大水深H₂" not in header_names
    assert len(captured_tables[0]["rows"][0]) == len(header_names)


def test_open_section_summary_table_prefers_current_table_snapshot_over_stale_calculated_nodes(monkeypatch):
    stale_nodes = [
        SimpleNamespace(
            structure_type=SimpleNamespace(value="明渠-矩形"),
            name="旧节点",
            section_params={"B": 1.5, "use_increase": True},
        )
    ]
    current_nodes = [
        SimpleNamespace(
            structure_type=SimpleNamespace(value="明渠-矩形"),
            name="当前节点",
            section_params={"B": 1.5, "use_increase": False},
        )
    ]
    captured = {}

    class _CapturingDialog:
        def __init__(self, _parent, nodes, _proj_settings, _auto_name, panel=None, config_only=False):
            _ = (panel, config_only)
            captured["nodes"] = nodes

        def exec(self):
            return cad_tools.QDialog.Accepted

    panel = _build_panel()
    panel.calculated_nodes = stale_nodes
    panel._build_nodes_from_table = lambda: current_nodes

    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _CapturingDialog)

    cad_tools.open_section_summary_table(panel)

    assert captured["nodes"] is current_nodes


def test_export_combined_dxf_passes_current_table_snapshot_to_section_summary(monkeypatch):
    docs = _patch_common(monkeypatch)
    stale_nodes = [
        SimpleNamespace(
            bottom_elevation=408.5,
            top_elevation=409.2,
            water_level=408.9,
            structure_type=SimpleNamespace(value="明渠-矩形"),
            is_transition=False,
            is_auto_inserted_channel=False,
            name="旧节点",
            section_params={"B": 1.5, "use_increase": True},
        )
    ]
    current_nodes = [
        SimpleNamespace(
            structure_type=SimpleNamespace(value="明渠-矩形"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            name="当前节点",
            flow_section="1",
            flow=1.0,
            roughness=0.014,
            slope_i=1 / 2000,
            section_params={"B": 1.5, "use_increase": False},
            water_depth=0.789,
            velocity=0.845,
            structure_height=1.19,
        )
    ]
    captured = {}

    class _ConfigOnlyDialog:
        def __init__(self, _parent, nodes, _proj_settings, _auto_name, panel=None, config_only=False):
            _ = panel
            captured["dialog_nodes"] = nodes
            captured["config_only"] = config_only

        def exec(self):
            return cad_tools.QDialog.Accepted

    panel = _build_panel()
    panel.calculated_nodes = stale_nodes
    panel._build_nodes_from_table = lambda: current_nodes

    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)

    def _fake_draw_section_summary_on_msp(*args, **kwargs):
        _ = args
        captured["summary_nodes"] = kwargs["nodes"]
        return 320.0, 180.0, 1

    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", _fake_draw_section_summary_on_msp)
    monkeypatch.setattr(
        cad_tools,
        "_compute_ip_preview_data",
        lambda *_a, **_k: ([["IP1"]], []),
    )
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)

    cad_tools.export_combined_dxf(panel)

    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert captured["config_only"] is True
    assert captured["dialog_nodes"] is current_nodes
    assert captured["summary_nodes"] is current_nodes
    debug_info = getattr(panel, "_last_section_summary_runtime_debug", None)
    assert isinstance(debug_info, dict)
    assert debug_info["summary_nodes_source"] == "current_table_snapshot"
    assert "calc_渠系计算算法内核" in debug_info["summary_module_file"]
    assert debug_info["summary_module_file"].endswith("生成断面汇总表.py")


def test_export_combined_dxf_uses_xxpipe_profile_branch_and_current_snapshot(monkeypatch):
    docs = _patch_common(monkeypatch)
    stale_nodes = [
        SimpleNamespace(
            station_MC=0.0,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            structure_type=SimpleNamespace(value="定向钻"),
            is_transition=False,
            is_auto_inserted_channel=False,
            name="旧节点",
            flow_section="1",
        )
    ]
    current_nodes = [
        SimpleNamespace(
            station_MC=0.0,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            structure_type=SimpleNamespace(value="定向钻"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            name="穿路段",
            flow_section="1",
        )
    ]
    captured = {}

    class _ConfigOnlyDialog:
        def __init__(self, _parent, nodes, _proj_settings, _auto_name, panel=None, config_only=False):
            _ = panel
            captured["dialog_nodes"] = nodes
            captured["config_only"] = config_only

        def exec(self):
            return cad_tools.QDialog.Accepted

    panel = _build_panel()
    panel.calculated_nodes = stale_nodes
    panel._build_nodes_from_table = lambda: current_nodes
    panel.channel_level_combo = _ComboStub("支管")

    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(cad_tools, "_build_panel_xxpipe_profile_data", lambda *_a, **_k: {"profile_text_nodes": current_nodes})

    def _fake_draw_profile_on_msp(*args, **kwargs):
        _ = args
        captured["profile_nodes"] = kwargs.get("xxpipe_profile_data", {})
        captured["export_mode"] = kwargs.get("export_mode")
        return 240.0, 120.0

    monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", _fake_draw_profile_on_msp)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))

    def _fake_compute_ip_preview_data(nodes, _station_prefix, _settings=None):
        captured["ip_nodes"] = nodes
        return [["IP1"]], nodes

    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", _fake_compute_ip_preview_data)
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)

    cad_tools.export_combined_dxf(panel)

    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert captured["config_only"] is True
    assert captured["dialog_nodes"] is current_nodes
    assert captured["export_mode"] == "xxpipe"
    assert captured["ip_nodes"] is current_nodes


def test_export_combined_dxf_prefers_tail_split_before_xxpipe_route_export_in_xxqu_mode(monkeypatch):
    docs = _patch_common(monkeypatch)
    captured = {}

    class _ConfigOnlyDialog:
        def __init__(self, _parent, nodes, _proj_settings, _auto_name, panel=None, config_only=False):
            _ = panel
            captured["dialog_nodes"] = nodes
            captured["config_only"] = config_only
            captured["dialog_mode"] = "standard"

        def exec(self):
            return cad_tools.QDialog.Accepted

    mixed_nodes = [
        SimpleNamespace(
            station_MC=0.0,
            bottom_elevation=410.0,
            top_elevation=411.0,
            water_level=410.5,
            structure_type=SimpleNamespace(value="明渠-圆形"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            name="渠道段",
            flow_section="1",
        ),
        SimpleNamespace(
            station_MC=100.0,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=True,
            name="苟家湾",
            flow_section="1",
        ),
        SimpleNamespace(
            station_MC=120.0,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            structure_type=SimpleNamespace(value="定向钻"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            name="大石包",
            flow_section="1",
        ),
    ]
    route_nodes = mixed_nodes[1:]

    panel = _build_panel(name="赛金", structure_type="有压管道")
    panel.calculated_nodes = list(mixed_nodes)
    panel._build_nodes_from_table = lambda: list(mixed_nodes)
    panel.channel_level_combo = _ComboStub("支渠")

    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)
    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(
        cad_tools,
        "TextExportSettingsDialog",
        type(
            "_Dialog",
            (),
            {
                "__init__": lambda self, *_a, **kwargs: captured.update({"dialog_mode": kwargs.get("mode")}) or setattr(self, "result", {}),
                "exec": lambda self: cad_tools.QDialog.Accepted,
            },
        ),
    )
    monkeypatch.setattr(
        cad_tools,
        "_resolve_tail_pressure_split_context",
        lambda *_a, **_k: {
            "channel_nodes": [mixed_nodes[0]],
            "channel_valid_nodes": [mixed_nodes[0]],
            "tail_nodes": list(route_nodes),
            "xxpipe_profile_data": {"profile_text_nodes": list(route_nodes)},
        },
        raising=False,
    )
    monkeypatch.setattr(
        cad_tools,
        "_draw_profile_on_msp",
        lambda *_a, **_k: captured.update({"single_profile_called": True}) or (240.0, 120.0),
    )
    monkeypatch.setattr(
        cad_tools,
        "_draw_tail_pressure_split_profile_on_msp",
        lambda *_a, **_k: captured.update({"tail_nodes": list(_a[3]), "tail_split_called": True}) or (240.0, 180.0),
        raising=False,
    )
    monkeypatch.setattr(
        cad_tools,
        "_draw_section_summary_on_msp",
        lambda *_a, **kwargs: captured.update({"summary_nodes": kwargs.get("nodes")}) or (320.0, 180.0, 1),
    )
    monkeypatch.setattr(
        cad_tools,
        "_compute_ip_preview_data",
        lambda nodes, _station_prefix, _settings=None: ([["IP1"]], nodes),
    )
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)

    cad_tools.export_combined_dxf(panel)

    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert captured["config_only"] is True
    assert [node.name for node in captured["dialog_nodes"]] == [node.name for node in mixed_nodes]
    assert [node.name for node in captured["summary_nodes"]] == [node.name for node in mixed_nodes]
    assert captured["dialog_mode"] == "standard"
    assert captured["tail_nodes"] == route_nodes
    assert captured["tail_split_called"] is True
    assert captured.get("single_profile_called") is not True


def test_resolve_xxpipe_export_source_nodes_returns_filtered_route_nodes_in_xxqu_route_mode():
    mixed_nodes = [
        SimpleNamespace(
            station_MC=0.0,
            structure_type=SimpleNamespace(value="明渠-圆形"),
            is_transition=False,
            is_auto_inserted_channel=False,
            name="渠道段",
        ),
        SimpleNamespace(
            station_MC=20.0,
            structure_type=SimpleNamespace(value="有压管道"),
            is_transition=True,
            is_auto_inserted_channel=False,
            name="过渡段",
        ),
        SimpleNamespace(
            station_MC=100.0,
            structure_type=SimpleNamespace(value="有压管道"),
            is_transition=False,
            is_auto_inserted_channel=False,
            name="苟家湾",
        ),
        SimpleNamespace(
            station_MC=110.0,
            structure_type=SimpleNamespace(value="定向钻"),
            is_transition=False,
            is_auto_inserted_channel=True,
            name="自动补点",
        ),
        SimpleNamespace(
            station_MC=120.0,
            structure_type=SimpleNamespace(value="定向钻"),
            is_transition=False,
            is_auto_inserted_channel=False,
            name="大石包",
        ),
    ]
    panel = _build_panel(name="赛金", structure_type="有压管道")
    panel.calculated_nodes = list(mixed_nodes)
    panel._build_nodes_from_table = lambda: list(mixed_nodes)
    panel.channel_level_combo = _ComboStub("支渠")
    panel._prepare_pressure_pipe_dialog_context = lambda nodes, settings=None, show_xxpipe_warning=False: {
        "xxpipe_route_mode": True,
        "route_import_targets": {
            "flow1-route2": {
                "nodes": [nodes[4], nodes[3]],
                "targets": [{"row_index": 4}, {"row_index": 3}],
            },
            "flow1-route1": {
                "nodes": [nodes[2], nodes[1], nodes[2]],
                "targets": [{"row_index": 2}, {"row_index": 1}, {"row_index": 2}],
            },
        },
    }

    resolved = cad_tools._resolve_xxpipe_export_source_nodes(panel, fallback_nodes=panel.calculated_nodes)

    assert resolved == [mixed_nodes[2], mixed_nodes[4]]


def test_export_combined_dxf_pushes_summary_below_tail_pressure_split_profile(monkeypatch):
    docs = _patch_common(monkeypatch)
    panel = _build_panel()
    panel.calculated_nodes = [
        _ProfileNode(
            station_MC=0.0,
            station_BC=0.0,
            station_EC=0.0,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="明渠-矩形"),
            name="明渠1",
            flow_section="1",
            in_out=None,
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            bottom_elevation=410.0,
            top_elevation=411.0,
            water_level=410.6,
        ),
        _ProfileNode(
            station_MC=100.0,
            station_BC=100.0,
            station_EC=100.0,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            name="末端压力管",
            flow_section="1",
            in_out=SimpleNamespace(value="进"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=True,
            bottom_elevation=409.0,
            top_elevation=0.0,
            water_level=0.0,
        ),
    ]
    captured = {}

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: False)
    monkeypatch.setattr(
        cad_tools,
        "_resolve_tail_pressure_split_context",
        lambda *_a, **_k: {
            "channel_nodes": panel.calculated_nodes[:1],
            "channel_valid_nodes": panel.calculated_nodes[:1],
            "tail_nodes": panel.calculated_nodes[1:],
            "xxpipe_profile_data": {"profile_text_nodes": panel.calculated_nodes[1:]},
        },
        raising=False,
    )
    monkeypatch.setattr(
        cad_tools,
        "_draw_tail_pressure_split_profile_on_msp",
        lambda *_a, **_k: (260.0, 280.0),
        raising=False,
    )
    monkeypatch.setattr(
        cad_tools,
        "_compute_ip_preview_data",
        lambda *_a, **_k: ([["IP1"]], []),
    )
    monkeypatch.setattr(
        cad_tools,
        "_draw_ip_table_on_msp",
        lambda _msp, _ox, oy, *_a, **_k: captured.update({"ip_oy": oy}),
    )

    def _fake_draw_section_summary_on_msp(*args, **kwargs):
        _ = args
        captured["below_y"] = kwargs["below_y"]
        return 320.0, 180.0, 1

    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", _fake_draw_section_summary_on_msp)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)

    cad_tools.export_combined_dxf(panel)

    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert captured["below_y"] == -300.0
    assert captured["ip_oy"] == -300.0


def test_export_combined_dxf_tail_split_keeps_upper_channel_horizontal_lines_with_hidden_tail_node(
    monkeypatch,
):
    docs = {}

    def _fake_new(_version):
        doc = _RecordingDoc()
        docs["doc"] = doc
        return doc

    ezdxf_stub = SimpleNamespace(
        new=_fake_new,
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)
    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _AcceptedTextDialog)
    monkeypatch.setattr(cad_tools, "_setup_profile_dxf_document", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_ensure_profile_layers", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cad_tools.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_a, **_k: ("C:/tmp/combined_hidden_tail_width.dxf", "DXF")),
    )

    panel = _build_panel()
    channel_nodes = [
        _make_profile_node(
            ip_no=1,
            mc=0.0,
            structure="明渠-矩形",
            name="明渠起点",
            bottom=410.0,
            top=411.0,
            water=410.5,
        ),
        _make_profile_node(
            ip_no=2,
            mc=100.0,
            structure="明渠-矩形",
            name="明渠终点",
            bottom=409.0,
            top=410.0,
            water=409.5,
        ),
        _make_profile_node(
            ip_no=3,
            mc=0.0,
            structure="明渠-矩形",
            name="隐藏补段",
            bottom=0.0,
            top=0.0,
            water=0.0,
            is_auto_inserted_channel=True,
        ),
    ]
    tail_nodes = [
        _make_profile_node(
            ip_no=4,
            mc=120.0,
            structure="有压管道",
            name="末端压力管",
            bottom=408.0,
            top=0.0,
            water=0.0,
            in_out="进",
        ),
    ]
    panel.calculated_nodes = channel_nodes + tail_nodes

    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", lambda *_a, **_k: ([["IP1"]], []))
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cad_tools,
        "_build_panel_xxpipe_profile_data",
        lambda *_a, **_k: {
            "profile_text_nodes": tail_nodes,
            "centerline_records": [{"station_mc": 120.0, "elevation": 100.0}],
            "centerline_points": [(120.0, 100.0)],
            "ip_records": [{"x": 120.0, "text": "IP4"}],
            "building_segments": [{"mid_mc": 120.0, "text": "末端压力管"}],
            "material_segments": [{"mid_mc": 120.0, "text": "钢管"}],
        },
    )

    cad_tools.export_combined_dxf(panel)

    msp = docs["doc"].modelspace()
    settings = cad_tools._normalize_text_export_settings({})
    expected_width = cad_tools._profile_meters_to_paper_mm(100.0, settings["scale_x"])
    assert docs["doc"].saved_path == "C:/tmp/combined_hidden_tail_width.dxf"
    assert _has_line(
        msp.line_records,
        (0.0, 45.0),
        (expected_width, 45.0),
        layer="纵断面_表格线框",
    )


def test_export_combined_dxf_tail_split_ignores_midstream_origin_breakpoint_in_upper_profile(
    monkeypatch,
):
    docs = {}

    def _fake_new(_version):
        doc = _RecordingDoc()
        docs["doc"] = doc
        return doc

    ezdxf_stub = SimpleNamespace(
        new=_fake_new,
        enums=SimpleNamespace(
            TextEntityAlignment=SimpleNamespace(
                MIDDLE="MIDDLE",
                MIDDLE_CENTER="MIDDLE_CENTER",
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "ezdxf", ezdxf_stub)
    monkeypatch.setattr(cad_tools, "TextExportSettingsDialog", _AcceptedTextDialog)
    monkeypatch.setattr(cad_tools, "_setup_profile_dxf_document", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_ensure_profile_layers", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cad_tools.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_a, **_k: ("C:/tmp/combined_tail_split_breakpoint.dxf", "DXF")),
    )

    panel = _build_panel()
    channel_nodes = [
        _make_profile_node(
            ip_no=1,
            mc=0.0,
            structure="明渠-矩形",
            name="明渠起点",
            bottom=410.0,
            top=411.0,
            water=410.5,
        ),
        _make_profile_node(
            ip_no=2,
            mc=100.0,
            structure="明渠-矩形",
            name="明渠中点",
            bottom=409.0,
            top=410.0,
            water=409.5,
        ),
        _make_profile_node(
            ip_no=3,
            mc=0.0,
            structure="渐变段",
            name="错误断点",
            bottom=408.6,
            top=409.6,
            water=409.1,
            is_transition=True,
        ),
        _make_profile_node(
            ip_no=4,
            mc=120.0,
            structure="明渠-矩形",
            name="明渠终点",
            bottom=408.4,
            top=409.4,
            water=408.9,
        ),
    ]
    tail_nodes = [
        _make_profile_node(
            ip_no=5,
            mc=150.0,
            structure="有压管道",
            name="末端压力管",
            bottom=408.0,
            top=0.0,
            water=0.0,
            in_out="进",
        ),
        _make_profile_node(
            ip_no=6,
            mc=180.0,
            structure="有压管道",
            name="末端压力管",
            bottom=407.5,
            top=0.0,
            water=0.0,
            in_out="出",
        ),
    ]
    panel.calculated_nodes = channel_nodes + tail_nodes

    monkeypatch.setattr(cad_tools, "fluent_error", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", lambda *_a, **_k: ([["IP1"]], []))
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cad_tools,
        "_build_panel_xxpipe_profile_data",
        lambda *_a, **_k: {
            "profile_text_nodes": tail_nodes,
            "centerline_records": [
                {"station_mc": 150.0, "elevation": 100.0},
                {"station_mc": 180.0, "elevation": 99.0},
            ],
            "centerline_points": [(150.0, 100.0), (180.0, 99.0)],
            "ip_records": [{"x": 150.0, "text": "IP5"}, {"x": 180.0, "text": "IP6"}],
            "building_segments": [{"mid_mc": 165.0, "text": "末端压力管"}],
            "material_segments": [{"mid_mc": 165.0, "text": "钢管"}],
        },
    )

    cad_tools.export_combined_dxf(panel)

    assert docs["doc"].saved_path == "C:/tmp/combined_tail_split_breakpoint.dxf"

    msp = docs["doc"].modelspace()
    upper_polylines = {}
    for record in msp.polyline_records:
        layer = record["dxfattribs"].get("layer")
        if layer in {"纵断面_渠底高程线", "纵断面_渠顶高程线", "纵断面_设计水位线"}:
            upper_polylines.setdefault(layer, []).append(record["points"])

    assert upper_polylines == {
        "纵断面_渠底高程线": [[(0.0, 410.0), (50.0, 409.0), (60.0, 408.4)]],
        "纵断面_渠顶高程线": [[(0.0, 411.0), (50.0, 410.0), (60.0, 409.4)]],
        "纵断面_设计水位线": [[(0.0, 410.5), (50.0, 409.5), (60.0, 408.9)]],
    }
    assert all(
        not _polyline_has_x_backtracking(points)
        for groups in upper_polylines.values()
        for points in groups
    )


def test_export_combined_dxf_tail_split_allows_strict_mixed_route_with_tunnel_gap(monkeypatch):
    docs = _patch_common(monkeypatch)
    panel = _build_panel(name="蒲家湾", structure_type="有压管道")
    panel.channel_level_combo = _ComboStub("支管")
    panel.calculated_nodes = _make_strict_mixed_tail_nodes()
    panel._build_nodes_from_table = lambda: list(panel.calculated_nodes)
    panel._prepare_pressure_pipe_dialog_context = lambda nodes, settings=None, show_xxpipe_warning=False: {
        "xxpipe_route_mode": True,
        "route_import_targets": {
            "flow1-route1": {
                "display_name": "蒲家湾整线1",
                "station_prefix": "",
                "nodes": list(nodes),
                "targets": [
                    {"row_index": 0, "label": "IP1", "station_mc": 0.0},
                    {"row_index": 1, "label": "IP2", "station_mc": 40.0},
                    {"row_index": 2, "label": "IP3", "station_mc": 80.0},
                    {"row_index": 3, "label": "IP4", "station_mc": 120.0},
                    {"row_index": 4, "label": "IP5", "station_mc": 160.0},
                ],
            }
        },
    }
    panel.get_pressure_pipe_longitudinal_nodes_for_export = lambda rows=None: {
        "flow1-row3": [
            {"chainage": 80.0, "elevation": 420.0, "turn_type": "NONE"},
            {"chainage": 160.0, "elevation": 415.0, "turn_type": "NONE"},
        ],
        "flow1-row5": [
            {"chainage": 80.0, "elevation": 420.0, "turn_type": "NONE"},
            {"chainage": 160.0, "elevation": 415.0, "turn_type": "NONE"},
        ],
    }
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda *_a, **_k: None,
        to_dict=lambda: {"pipes": {}, "routes": {}},
    )
    errors = []
    captured = {}

    class _ConfigOnlyDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return cad_tools.QDialog.Accepted

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", lambda *_a, **_k: ([["IP1"]], panel.calculated_nodes))

    def _fake_draw_tail_pressure_split_profile_on_msp(
        _msp,
        _channel_nodes,
        _channel_valid_nodes,
        tail_nodes,
        _profile_settings,
        _station_prefix,
        *,
        layer_prefix="",
        xxpipe_profile_data=None,
    ):
        _ = layer_prefix
        captured["tail_nodes"] = list(tail_nodes)
        captured["profile"] = dict(xxpipe_profile_data or {})
        return 260.0, 180.0

    monkeypatch.setattr(
        cad_tools,
        "_draw_tail_pressure_split_profile_on_msp",
        _fake_draw_tail_pressure_split_profile_on_msp,
    )

    cad_tools.export_combined_dxf(panel)

    assert not errors
    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert [node.station_MC for node in captured["tail_nodes"]] == [80.0, 120.0, 160.0]
    assert [node.station_MC for node in captured["profile"]["profile_text_nodes"]] == [80.0, 120.0, 160.0]
    assert [record["identity"] for record in captured["profile"]["centerline_records"]] == [
        "flow1-row3",
        "flow1-row5",
    ]


def test_export_combined_dxf_tail_split_shows_detailed_gap_for_strict_mixed_route(monkeypatch):
    docs = _patch_common(monkeypatch)
    panel = _build_panel(name="蒲家湾", structure_type="有压管道")
    panel.channel_level_combo = _ComboStub("支管")
    panel.calculated_nodes = _make_strict_mixed_tail_nodes()
    panel._build_nodes_from_table = lambda: list(panel.calculated_nodes)
    panel._prepare_pressure_pipe_dialog_context = lambda nodes, settings=None, show_xxpipe_warning=False: {
        "xxpipe_route_mode": True,
        "route_import_targets": {
            "flow1-route1": {
                "display_name": "蒲家湾整线1",
                "station_prefix": "",
                "nodes": list(nodes),
                "targets": [
                    {"row_index": 0, "label": "IP1", "station_mc": 0.0},
                    {"row_index": 1, "label": "IP2", "station_mc": 40.0},
                    {"row_index": 2, "label": "IP3", "station_mc": 80.0},
                    {"row_index": 3, "label": "IP4", "station_mc": 120.0},
                    {"row_index": 4, "label": "IP5", "station_mc": 160.0},
                ],
            }
        },
    }
    panel.get_pressure_pipe_longitudinal_nodes_for_export = lambda rows=None: {
        "flow1-row3": [
            {"chainage": 80.0, "elevation": 420.0, "turn_type": "NONE"},
            {"chainage": 120.0, "elevation": 417.0, "turn_type": "NONE"},
        ],
        "flow1-row5": [
            {"chainage": 80.0, "elevation": 420.0, "turn_type": "NONE"},
            {"chainage": 120.0, "elevation": 417.0, "turn_type": "NONE"},
        ],
    }
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda *_a, **_k: None,
        to_dict=lambda: {"pipes": {}, "routes": {}},
    )
    errors = []

    class _ConfigOnlyDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return cad_tools.QDialog.Accepted

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: False)
    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", lambda *_a, **_k: ([["IP1"]], panel.calculated_nodes))

    cad_tools.export_combined_dxf(panel)

    assert errors
    assert "doc" not in docs or docs["doc"].saved_path is None
    assert "蒲家湾整线1" in errors[-1][2]
    assert "导入失败：纵断面范围不够" in errors[-1][2]
    assert "需要覆盖到桩号 160.000 m" in errors[-1][2]
    assert "当前导入的纵断面只到 120.000 m" in errors[-1][2]
    assert "未覆盖节点：IP5@0+160.000" in errors[-1][2]
    assert "没有匹配到对应整线" not in errors[-1][2]


def test_export_combined_dxf_translates_missing_xxpipe_longitudinal_error(monkeypatch):
    _patch_common(monkeypatch)
    panel = _build_panel(name="穿路段", structure_type="定向钻")
    errors = []

    class _ConfigOnlyDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return cad_tools.QDialog.Accepted

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        cad_tools,
        "_build_panel_xxpipe_profile_data",
        lambda *_a, **_k: (_ for _ in ()).throw(
            ValueError("以下节点缺少可用的 xx管 轴线高程覆盖：\n1::穿路段 缺少轴线纵断面")
        ),
    )

    cad_tools.export_combined_dxf(panel)

    assert errors
    assert "对应整线还没有导入纵断面DXF" in errors[-1][2]
    assert "请先到表3的有压管道水力计算中导入后再导出" in errors[-1][2]
    assert "缺少轴线纵断面" not in errors[-1][2]


def test_export_combined_dxf_shows_detailed_xxpipe_coverage_error(monkeypatch):
    _patch_common(monkeypatch)
    panel = _build_panel(name="穿路段", structure_type="定向钻")
    errors = []
    detail_message = (
        "整线：流量段1 整线1\n"
        "导入失败：纵断面范围不够\n"
        "这条整线需要覆盖到桩号 80.000 m，但当前导入的纵断面只到 50.000 m。\n"
        "当前还差 30000.0 mm（30.000 m），已超过程序允许的 1.0 mm 误差。\n"
        "请在 CAD 中把纵断面末端至少延长到 80.000 m 后重新导入。\n"
        "未覆盖节点：IP2@0+080.000"
    )

    class _ConfigOnlyDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return cad_tools.QDialog.Accepted

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        cad_tools,
        "_build_panel_xxpipe_profile_data",
        lambda *_a, **_k: (_ for _ in ()).throw(
            ValueError(detail_message)
        ),
    )

    cad_tools.export_combined_dxf(panel)

    assert errors
    assert errors[-1][2] == detail_message


def test_export_combined_dxf_keeps_using_full_route_profile_when_segment_cache_only_has_one_point(monkeypatch):
    docs = _patch_common(monkeypatch)
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    errors = []
    captured = {}

    route_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "turn_type": "NONE"},
        {"chainage": 50.0, "elevation": 95.0, "turn_type": "NONE"},
        {"chainage": 100.0, "elevation": 90.0, "turn_type": "NONE"},
    ]
    current_nodes = [
        _ProfileNode(
            ip_number=1,
            station_MC=0.0,
            station_BC=0.0,
            station_EC=0.0,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="定向钻"),
            name="穿路段",
            flow_section="1",
            in_out=SimpleNamespace(value="进"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            section_params={"pipe_material": "球墨铸铁管", "D": 1.2},
            pressure_pipe_row_identity="1::穿路段",
        ),
        _ProfileNode(
            ip_number=2,
            station_MC=50.0,
            station_BC=50.0,
            station_EC=50.0,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="定向钻"),
            name="穿路段",
            flow_section="1",
            in_out=None,
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            section_params={"pipe_material": "球墨铸铁管", "D": 1.2},
            pressure_pipe_row_identity="1::穿路段",
        ),
        _ProfileNode(
            ip_number=3,
            station_MC=100.0,
            station_BC=100.0,
            station_EC=100.0,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="定向钻"),
            name="穿路段",
            flow_section="1",
            in_out=SimpleNamespace(value="出"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            section_params={"pipe_material": "球墨铸铁管", "D": 1.2},
            pressure_pipe_row_identity="1::穿路段",
        ),
    ]
    group = SimpleNamespace(
        storage_key="1::穿路段",
        route_key="flow1-route1",
        route_display_name="流量段1 整线1",
        display_name="穿路段",
        name="穿路段",
        identity="1::穿路段",
        flow_section="1",
        segment_start_mc=0.0,
        segment_end_mc=100.0,
    )

    panel.calculated_nodes = current_nodes
    panel._build_nodes_from_table = lambda: current_nodes
    panel._build_settings = lambda: _Settings()
    panel._text_export_settings = {}
    panel._custom_pressurized_pipe_params = {}
    panel.channel_name_edit = _TextStub("双桥支管")
    panel.channel_level_combo = _ComboStub("支管")
    panel.window = lambda: panel
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda key: None,
        to_dict=lambda: {
            "routes": {
                "flow1-route1": {
                    "display_name": "流量段1 整线1",
                    "longitudinal_nodes": route_nodes,
                    "profile_segments": [
                        {
                            "segment_identity": "1::穿路段",
                            "source_kind": "non_tunnel_dxf",
                            "start_mc": 0.0,
                            "end_mc": 100.0,
                            "longitudinal_nodes": [
                                {"chainage": 0.0, "elevation": 100.0, "turn_type": "NONE"},
                            ],
                        }
                    ],
                }
            }
        },
    )
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: [group]

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)

    class _ConfigOnlyDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return cad_tools.QDialog.Accepted

    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", lambda *_a, **_k: ([["IP1"]], current_nodes))

    def _fake_draw_profile_on_msp(*args, **kwargs):
        captured["profile"] = kwargs.get("xxpipe_profile_data", {})
        return 240.0, 120.0

    monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", _fake_draw_profile_on_msp)

    cad_tools.export_combined_dxf(panel)

    assert not errors
    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert captured["profile"]["centerline_points"] == [
        (0.0, 100.0),
        (50.0, 95.0),
        (100.0, 90.0),
    ]


def test_export_combined_dxf_uses_route_profile_when_boundary_segment_misses_row_station(monkeypatch):
    docs = _patch_common(monkeypatch)
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    errors = []
    captured = {}

    route_nodes = [
        {"chainage": 2739.785, "elevation": 348.401, "turn_type": "NONE"},
        {"chainage": 6526.755, "elevation": 325.770, "turn_type": "NONE"},
    ]
    current_nodes = [
        _ProfileNode(
            ip_number=19,
            station_MC=2739.785,
            station_BC=2739.785,
            station_EC=2739.785,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            name="蒲支压力段",
            flow_section="1",
            in_out=SimpleNamespace(value="进"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=True,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            section_params={"pipe_material": "球墨铸铁管", "D": 1.2},
            pressure_pipe_row_identity="flow1-row19",
        )
    ]
    group = SimpleNamespace(
        storage_key="flow1-row19",
        route_key="flow1-route2",
        route_display_name="蒲支整线2",
        display_name="蒲支压力段",
        name="蒲支压力段",
        identity="flow1-row19",
        flow_section="1",
        segment_start_mc=2673.115,
        segment_end_mc=2739.785,
    )

    panel.calculated_nodes = current_nodes
    panel._build_nodes_from_table = lambda: current_nodes
    panel._build_settings = lambda: _Settings()
    panel._text_export_settings = {}
    panel._custom_pressurized_pipe_params = {}
    panel.channel_name_edit = _TextStub("蒲支")
    panel.channel_level_combo = _ComboStub("支管")
    panel.window = lambda: panel
    panel._prepare_pressure_pipe_dialog_context = lambda nodes, settings=None, show_xxpipe_warning=False: {
        "xxpipe_route_mode": True,
        "route_import_targets": {
            "flow1-route2": {
                "display_name": "蒲支整线2",
                "station_prefix": "蒲支",
                "nodes": list(nodes),
                "targets": [
                    {"row_index": 0, "label": "flow1-row19", "station_mc": 2739.785},
                ],
            }
        },
    }
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda key: SimpleNamespace(
            longitudinal_nodes=[
                {"chainage": 2673.115, "elevation": 347.283, "turn_type": "NONE"},
                {"chainage": 2739.780, "elevation": 348.233, "turn_type": "NONE"},
            ]
        ) if key == "flow1-row19" else None,
        to_dict=lambda: {
            "routes": {
                "flow1-route2": {
                    "display_name": "蒲支整线2",
                    "longitudinal_nodes": route_nodes,
                }
            }
        },
    )
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: [group]

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)

    class _ConfigOnlyDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return cad_tools.QDialog.Accepted

    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", lambda *_a, **_k: ([["IP19"]], current_nodes))

    def _fake_draw_profile_on_msp(*args, **kwargs):
        captured["profile"] = kwargs.get("xxpipe_profile_data", {})
        return 240.0, 120.0

    monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", _fake_draw_profile_on_msp)

    cad_tools.export_combined_dxf(panel)

    assert not errors
    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert [record["identity"] for record in captured["profile"]["centerline_records"]] == ["flow1-row19"]
    assert captured["profile"]["centerline_points"] == [(2739.785, 348.401)]


def test_export_combined_dxf_uses_same_station_identity_candidates_when_route_identity_shifts(monkeypatch):
    docs = _patch_common(monkeypatch)
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    errors = []
    captured = {}

    route_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "turn_type": "NONE"},
        {"chainage": 100.0, "elevation": 90.0, "turn_type": "NONE"},
    ]
    current_nodes = [
        _ProfileNode(
            ip_number=1,
            station_MC=0.0,
            station_BC=0.0,
            station_EC=0.0,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="定向钻"),
            name="穿路段",
            flow_section="1",
            in_out=SimpleNamespace(value="进"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=False,
            bottom_elevation=10.0,
            top_elevation=11.0,
            water_level=10.5,
            section_params={"pipe_material": "球墨铸铁管", "D": 1.2},
            pressure_pipe_row_identity="",
        ),
        _ProfileNode(
            ip_number=2,
            station_MC=0.0,
            station_BC=0.0,
            station_EC=0.0,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            name="",
            flow_section="1",
            in_out=None,
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=True,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            section_params={"pipe_material": "球墨铸铁管", "D": 1.2},
            pressure_pipe_row_identity="flow1-row1",
        ),
    ]

    panel.calculated_nodes = current_nodes
    panel._build_nodes_from_table = lambda: current_nodes
    panel._build_settings = lambda: _Settings()
    panel._text_export_settings = {}
    panel._custom_pressurized_pipe_params = {}
    panel.channel_name_edit = _TextStub("双桥支管")
    panel.channel_level_combo = _ComboStub("支管")
    panel.window = lambda: panel
    panel.get_pressure_pipe_longitudinal_nodes_for_export = lambda rows=None: {
        "flow1-row1": route_nodes,
    }
    panel._pressure_pipe_manager = SimpleNamespace(to_dict=lambda: {"pipes": {}, "routes": {}})

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)

    class _ConfigOnlyDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return cad_tools.QDialog.Accepted

    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", lambda *_a, **_k: ([["IP1"]], current_nodes))

    def _fake_draw_profile_on_msp(*args, **kwargs):
        captured["profile"] = kwargs.get("xxpipe_profile_data", {})
        return 240.0, 120.0

    monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", _fake_draw_profile_on_msp)

    cad_tools.export_combined_dxf(panel)

    assert not errors
    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert captured["profile"]["centerline_points"] == [(0.0, 100.0)]
    assert [record["identity"] for record in captured["profile"]["centerline_records"]] == ["flow1-row1"]


def test_export_combined_dxf_keeps_route_profile_for_cross_flow_boundary_row(monkeypatch):
    docs = _patch_common(monkeypatch)
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    errors = []
    captured = {}

    route_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "turn_type": "NONE"},
        {"chainage": 100.0, "elevation": 95.0, "turn_type": "NONE"},
        {"chainage": 200.0, "elevation": 90.0, "turn_type": "NONE"},
    ]
    current_nodes = [
        _ProfileNode(
            ip_number=62,
            station_MC=90.0,
            station_BC=90.0,
            station_EC=90.0,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            name="",
            flow_section="1",
            in_out=None,
            is_transition=True,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=True,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            section_params={"pipe_material": "球墨铸铁管", "D": 1.2},
            pressure_pipe_row_identity="flow1-row62",
        ),
        _ProfileNode(
            ip_number=63,
            station_MC=100.0,
            station_BC=100.0,
            station_EC=100.0,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            name="",
            flow_section="2",
            in_out=None,
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=True,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            section_params={"pipe_material": "球墨铸铁管", "D": 1.2},
            pressure_pipe_row_identity="flow2-row63",
        ),
    ]
    group = SimpleNamespace(
        group_mode="unnamed_row_segment",
        storage_key="flow2-row63",
        route_key="flow1-route1",
        route_display_name="遂广连续整线",
        display_name="流量段2 第63行有压管道",
        name="",
        identity="flow2-row63",
        flow_section="2",
        segment_start_mc=100.0,
        segment_end_mc=100.0,
        target_row_index=1,
        upstream_row_index=0,
        route_start_row_index=0,
    )

    panel.calculated_nodes = current_nodes
    panel._build_nodes_from_table = lambda: current_nodes
    panel._build_settings = lambda: _Settings()
    panel._text_export_settings = {}
    panel._custom_pressurized_pipe_params = {}
    panel.channel_name_edit = _TextStub("双桥支管")
    panel.channel_level_combo = _ComboStub("支管")
    panel.window = lambda: panel
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda key: None,
        to_dict=lambda: {
            "routes": {
                "flow1-route1": {
                    "display_name": "遂广连续整线",
                    "longitudinal_nodes": route_nodes,
                }
            }
        },
    )
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: [group]

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)

    class _ConfigOnlyDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return cad_tools.QDialog.Accepted

    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", lambda *_a, **_k: ([["IP1"]], current_nodes))

    def _fake_draw_profile_on_msp(*args, **kwargs):
        captured["profile"] = kwargs.get("xxpipe_profile_data", {})
        return 240.0, 120.0

    monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", _fake_draw_profile_on_msp)

    cad_tools.export_combined_dxf(panel)

    assert not errors
    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert [record["identity"] for record in captured["profile"]["centerline_records"]] == ["flow2-row63"]


def test_export_combined_dxf_falls_back_to_route_profile_when_segment_misses_boundary_station(monkeypatch):
    docs = _patch_common(monkeypatch)
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    errors = []
    captured = {}

    route_nodes = [
        {"chainage": 2739.785, "elevation": 348.4, "turn_type": "NONE"},
        {"chainage": 6526.755, "elevation": 325.77, "turn_type": "NONE"},
    ]
    current_nodes = [
        _ProfileNode(
            ip_number=19,
            station_MC=2739.785,
            station_BC=2739.785,
            station_EC=2739.785,
            turn_angle=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            name="",
            flow_section="1",
            in_out=None,
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=True,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            section_params={"pipe_material": "球墨铸铁管", "D": 1.2},
            pressure_pipe_row_identity="flow1-row19",
        ),
    ]
    group = SimpleNamespace(
        group_mode="unnamed_row_segment",
        storage_key="flow1-row19",
        route_key="flow1-route2",
        route_display_name="蒲支整线2",
        display_name="流量段1 第19行有压管道",
        name="",
        identity="flow1-row19",
        flow_section="1",
        segment_start_mc=2673.115,
        segment_end_mc=2739.785,
        target_row_index=0,
        upstream_row_index=-1,
        route_start_row_index=0,
    )

    panel.calculated_nodes = current_nodes
    panel._build_nodes_from_table = lambda: current_nodes
    panel._build_settings = lambda: _Settings()
    panel._text_export_settings = {}
    panel._custom_pressurized_pipe_params = {}
    panel.channel_name_edit = _TextStub("蒲支")
    panel.channel_level_combo = _ComboStub("支管")
    panel.window = lambda: panel
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda key: None,
        to_dict=lambda: {
            "routes": {
                "flow1-route2": {
                    "display_name": "蒲支整线2",
                    "longitudinal_nodes": route_nodes,
                    "profile_segments": [
                        {
                            "segment_identity": "flow1-row19",
                            "source_kind": "non_tunnel_dxf",
                            "start_mc": 2673.115,
                            "end_mc": 2739.785,
                            "longitudinal_nodes": [
                                {"chainage": 2673.115, "elevation": 349.0, "turn_type": "NONE"},
                                {"chainage": 2700.0, "elevation": 348.8, "turn_type": "NONE"},
                            ],
                        }
                    ],
                }
            }
        },
    )
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: [group]

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)

    class _ConfigOnlyDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return cad_tools.QDialog.Accepted

    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", lambda *_a, **_k: ([["IP19"]], current_nodes))

    def _fake_draw_profile_on_msp(*args, **kwargs):
        captured["profile"] = kwargs.get("xxpipe_profile_data", {})
        return 240.0, 120.0

    monkeypatch.setattr(cad_tools, "_draw_profile_on_msp", _fake_draw_profile_on_msp)

    cad_tools.export_combined_dxf(panel)

    assert not errors
    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert [record["identity"] for record in captured["profile"]["centerline_records"]] == ["flow1-row19"]


def test_translate_xxpipe_export_error_distinguishes_identity_mismatch_from_missing_import():
    translated = cad_tools._translate_xxpipe_export_error(
        ValueError("以下节点未匹配到可用的整线纵断面：\nflow1-row1")
    )

    assert translated is not None
    assert "flow1-row1" in translated
    assert "还没有导入" not in translated


def test_export_combined_dxf_allows_relaxed_xxqu_blank_centerline_and_shows_guidance(monkeypatch):
    docs = _patch_common(monkeypatch)
    panel = _build_panel(name="南干支线", structure_type="有压管道")
    panel.channel_level_combo = _ComboStub("支渠")
    infos = []
    errors = []

    class _ConfigOnlyDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return cad_tools.QDialog.Accepted

    current_nodes = [
        SimpleNamespace(
            station_MC=0.0,
            bottom_elevation=0.0,
            top_elevation=0.0,
            water_level=0.0,
            structure_type=SimpleNamespace(value="有压管道"),
            is_transition=False,
            is_auto_inserted_channel=False,
            is_inverted_siphon=False,
            is_pressure_pipe=True,
            name="南干支线",
            flow_section="1",
        )
    ]

    monkeypatch.setattr(cad_tools, "_is_panel_xxpipe_mode", lambda *_a, **_k: True)
    monkeypatch.setattr(cad_tools, "SectionSummaryDialog", _ConfigOnlyDialog)
    monkeypatch.setattr(cad_tools, "_safe_qt_parent", lambda value: value)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: infos.append(args))
    monkeypatch.setattr(cad_tools, "fluent_error", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        cad_tools,
        "_build_panel_xxpipe_profile_data",
        lambda *_a, **_k: {
            "profile_text_nodes": current_nodes,
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
    monkeypatch.setattr(cad_tools, "_draw_section_summary_on_msp", lambda *_a, **_k: (320.0, 180.0, 1))
    monkeypatch.setattr(cad_tools, "_draw_ip_table_on_msp", lambda *_a, **_k: None)
    monkeypatch.setattr(cad_tools, "_compute_ip_preview_data", lambda *_a, **_k: ([["IP1"]], current_nodes))

    cad_tools.export_combined_dxf(panel)

    assert docs["doc"].saved_path == "C:/tmp/combined_test.dxf"
    assert not errors
    assert any("导入纵断面轴线DXF" in args[2] for args in infos)
