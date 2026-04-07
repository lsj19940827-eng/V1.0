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


def test_export_combined_dxf_translates_incomplete_xxpipe_coverage_error(monkeypatch):
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
            ValueError("以下节点缺少可用的 xx管 轴线高程覆盖：\n1::穿路段@0+080.000")
        ),
    )

    cad_tools.export_combined_dxf(panel)

    assert errors
    assert "已导入纵断面DXF，但未覆盖整线全部桩号" in errors[-1][2]
    assert "请重新导入完整纵断面后再导出" in errors[-1][2]
    assert "@0+080.000" not in errors[-1][2]


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
