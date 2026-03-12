# -*- coding: utf-8 -*-
"""合并导出 DXF（纵断面 + 断面汇总 + IP表）行为单元测试。"""

from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
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


def _build_panel():
    node = SimpleNamespace(
        bottom_elevation=408.5,
        top_elevation=409.2,
        water_level=408.9,
        structure_type=SimpleNamespace(value="明渠-矩形"),
        is_transition=False,
        is_auto_inserted_channel=False,
        name="N1",
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
