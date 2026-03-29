# -*- coding: utf-8 -*-
"""表3与水位详情口径统一回归测试。"""

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_formula_dialog_module():
    module_path = next(Path(".").glob("**/water_profile/formula_dialog.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_loss_alignment_formula_dialog_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_panel_module():
    module_path = next(Path(".").glob("**/water_profile/panel.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_loss_alignment_panel_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture_formula_dialog(monkeypatch, module):
    captured = {}

    class _FakeFormulaDialog:
        def __init__(self, parent, title, sections):
            captured["parent"] = parent
            captured["title"] = title
            captured["sections"] = sections

    monkeypatch.setattr(module, "FormulaDialog", _FakeFormulaDialog)
    return captured


def _build_panel(panel_module, start_level=565.1160):
    panel = panel_module.WaterProfilePanel.__new__(panel_module.WaterProfilePanel)
    panel._build_settings = lambda: SimpleNamespace(start_water_level=start_level)
    return panel


def _make_node(**overrides):
    defaults = {
        "name": "",
        "is_transition": False,
        "is_diversion_gate": False,
        "head_loss_transition": 0.0,
        "head_loss_total": 0.0,
        "head_loss_bend": 0.0,
        "head_loss_friction": 0.0,
        "head_loss_local": 0.0,
        "head_loss_reserve": 0.0,
        "head_loss_gate": 0.0,
        "head_loss_siphon": 0.0,
        "head_loss_cumulative": 0.0,
        "water_level": 0.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _build_text_blob(sections):
    return "\n".join(
        "\n".join(str(section.get(key, "")) for key in ("title", "values", "content", "formula"))
        for section in sections
    )


def test_total_loss_details_exclude_preceding_transition_row(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    panel_module = _load_panel_module()
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    captured = {}

    monkeypatch.setattr(
        formula_module,
        "show_total_loss_dialog",
        lambda parent, node_name, details: captured.update(
            parent=parent, node_name=node_name, details=details
        ),
    )

    panel = _build_panel(panel_module)
    nodes = [
        _make_node(name="上游普通行", head_loss_total=0.0055),
        _make_node(name="渐变段", is_transition=True, head_loss_transition=0.0021),
        _make_node(name="燕儿包", head_loss_total=0.0081, head_loss_friction=0.0081),
    ]

    panel_module.WaterProfilePanel._show_total_calc_details(panel, 2, nodes[2], nodes)

    assert captured["node_name"] == "燕儿包"
    assert captured["details"]["head_loss_total"] == 0.0081
    assert captured["details"]["head_loss_transition"] == 0.0


def test_water_level_details_distinguish_row_loss_transition_and_step_drop(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    panel_module = _load_panel_module()
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    captured = {}

    monkeypatch.setattr(
        formula_module,
        "show_water_level_dialog",
        lambda parent, node_name, details: captured.update(
            parent=parent, node_name=node_name, details=details
        ),
    )

    panel = _build_panel(panel_module)
    nodes = [
        _make_node(name="上一步普通行", water_level=564.6420, head_loss_cumulative=0.4738, head_loss_total=0.0055),
        _make_node(name="渐变段", is_transition=True, head_loss_transition=0.0021, head_loss_cumulative=0.4759),
        _make_node(
            name="燕儿包",
            water_level=564.6320,
            head_loss_total=0.0081,
            head_loss_friction=0.0081,
            head_loss_cumulative=0.4840,
        ),
    ]

    panel_module.WaterProfilePanel._show_water_level_details(panel, 2, nodes[2], nodes)

    details = captured["details"]
    assert captured["node_name"] == "燕儿包"
    assert details["prev_level"] == 564.6420
    assert details["total_loss"] == 0.0081
    assert details["transition_step_loss"] == 0.0021
    assert details["step_drop"] == 0.0102
    assert details["cumulative"] == 0.4840
    assert details["water_level"] == 564.6320


def test_total_loss_dialog_describes_regular_row_loss_only(monkeypatch):
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_total_loss_dialog(
        None,
        "燕儿包",
        {
            "head_loss_bend": 0.0,
            "head_loss_transition": 0.0,
            "head_loss_friction": 0.0081,
            "head_loss_local": 0.0,
            "head_loss_reserve": 0.0,
            "head_loss_gate": 0.0,
            "head_loss_siphon": 0.0,
            "head_loss_total": 0.0081,
        },
    )

    text_blob = _build_text_blob(captured["sections"])

    assert captured["title"] == "燕儿包 - 总水头损失计算详情"
    assert "普通行自身损失" in text_blob
    assert "不含前方单独渐变段行" in text_blob
    assert "0.0081" in text_blob
    assert "h_{tr}" not in text_blob


def test_water_level_dialog_shows_both_row_loss_and_step_drop(monkeypatch):
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_water_level_dialog(
        None,
        "燕儿包",
        {
            "is_first": False,
            "is_gate": False,
            "prev_level": 564.6420,
            "start_level": 565.1160,
            "cumulative": 0.4840,
            "water_level": 564.6320,
            "total_loss": 0.0081,
            "transition_step_loss": 0.0021,
            "step_drop": 0.0102,
            "hf": 0.0081,
            "hj": 0.0,
            "hw": 0.0,
            "h_reserve": 0.0,
            "h_gate": 0.0,
            "h_siphon": 0.0,
        },
    )

    text_blob = _build_text_blob(captured["sections"])

    assert captured["title"] == "燕儿包 - 水位计算详情"
    assert "本普通行总水头损失" in text_blob
    assert "中间渐变段小计" in text_blob
    assert "本步总落差" in text_blob
    assert "0.0081" in text_blob
    assert "0.0021" in text_blob
    assert "0.0102" in text_blob
    assert "多出的部分来自上一普通节点与本行之间的渐变段" in text_blob
    assert "564.6318" not in text_blob
