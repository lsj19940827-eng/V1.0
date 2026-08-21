# -*- coding: utf-8 -*-
"""匿名有压管道损失弹窗口径回归测试。"""

import importlib.util
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_formula_dialog_module():
    module_path = next(Path(".").glob("**/water_profile/formula_dialog.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_pressure_pipe_formula_dialog_test", module_path)
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


def _build_text_blob(sections):
    return "\n".join(
        "\n".join(str(section.get(key, "")) for key in ("title", "values", "content", "formula"))
        for section in sections
    )


def test_show_friction_loss_dialog_supports_pressure_pipe_fmb(monkeypatch):
    QApplication.instance() or QApplication([])
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_friction_loss_dialog(
        None,
        "匿名有压管道",
        {
            "method": "pressure_pipe_fmb",
            "Q_m3s": 1.8,
            "Q_m3h": 6480.0,
            "D_m": 1.0,
            "d_mm": 1000.0,
            "L_effective": 80.0,
            "L_mc": 100.0,
            "L_transition": 20.0,
            "arc1_half": 5.0,
            "arc2_half": 7.5,
            "pipe_material": "预应力钢筒混凝土管",
            "f": 1.312e6,
            "m": 2.0,
            "b": 5.33,
            "hf": 0.450997,
        },
    )

    titles = [section.get("title", "") for section in captured["sections"]]
    text_blob = _build_text_blob(captured["sections"])

    assert captured["title"] == "匿名有压管道 - 沿程水头损失计算详情"
    assert titles[0] == "1. 沿程水头损失公式（FMB）"
    assert "管材  预应力钢筒混凝土管" in text_blob
    assert "Q = 1.8000" in text_blob
    assert "h_f = 0.4510" in text_blob
    assert "上行半弧长（核查，不扣减）" in text_blob
    assert r"\frac{L_{arc,1}}" not in text_blob


def test_show_bend_loss_dialog_supports_pressure_pipe_bend(monkeypatch):
    QApplication.instance() or QApplication([])
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_bend_loss_dialog(
        None,
        "匿名有压管道",
        {
            "method": "pressure_pipe_bend",
            "D_m": 1.0,
            "turn_radius_m": 3.0,
            "turn_angle_deg": 45.0,
            "xi_90": 0.48,
            "gamma": 0.6875,
            "xi_bend": 0.33,
            "V_m_s": 2.0,
            "hj": 0.067278,
            "hw": 0.067278,
        },
    )

    titles = [section.get("title", "") for section in captured["sections"]]
    text_blob = _build_text_blob(captured["sections"])

    assert captured["title"] == "匿名有压管道 - 弯道附加水头损失计算详情"
    assert titles[0] == "1. 承压弯头局部损失公式"
    assert "90°基准系数" in text_blob
    assert "角度修正系数" in text_blob
    assert "h_j = 0.0673" in text_blob


def test_show_bend_loss_dialog_displays_adjacent_half_bend_allocation(monkeypatch):
    """普通明流详情应同时展示上游后半弯道和当前前半弯道。"""
    QApplication.instance() or QApplication([])
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_bend_loss_dialog(
        None,
        "当前节点",
        {
            "method": "open_channel_interval_halves",
            "upstream_node_name": "上游弯道",
            "downstream_node_name": "当前弯道",
            "upstream_full_loss": 0.020000,
            "downstream_full_loss": 0.012000,
            "upstream_half_loss": 0.010000,
            "downstream_half_loss": 0.006000,
            "hw": 0.016000,
            "upstream_full_details": {
                "n": 0.014,
                "L": 20.0,
                "v": 2.0,
                "R": 1.0,
                "B": 2.0,
                "Rc": 50.0,
            },
            "downstream_full_details": {
                "n": 0.016,
                "L": 12.0,
                "v": 1.6,
                "R": 0.8,
                "B": 2.4,
                "Rc": 30.0,
            },
        },
    )

    titles = [section.get("title", "") for section in captured["sections"]]
    text_blob = _build_text_blob(captured["sections"])
    assert titles[1] == "2. 本行MC区间分配公式"
    assert "上游弯道后半段" in text_blob
    assert "当前弯道前半段" in text_blob
    assert "0.010000 + 0.006000" in text_blob
    assert "当前节点完整弯道核查值" in text_blob


def test_bend_loss_column_uses_additional_term_label_and_keeps_legacy_alias():
    """新表头应明确附加损失，同时旧表头仍能查到同一公式说明。"""
    module = _load_formula_dialog_module()

    assert "弯道附加水头损失" in module.DOUBLE_CLICK_COLUMNS
    assert (
        module.COLUMN_FORMULAS["弯道水头损失"]
        is module.COLUMN_FORMULAS["弯道附加水头损失"]
    )


def test_show_pressure_pipe_loss_dialog_supports_row_level_display(monkeypatch):
    QApplication.instance() or QApplication([])
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_pressure_pipe_loss_dialog(
        None,
        "行5",
        {
            "pressure_pipe_display_is_row_sum": True,
            "pressure_pipe_display_loss": 0.0315,
            "head_loss_friction": 0.0215,
            "head_loss_bend": 0.0100,
            "head_loss_local": 0.0,
        },
    )

    text_blob = _build_text_blob(captured["sections"])

    assert captured["title"] == "行5 - 倒虹吸/有压管道水头损失详情"
    assert "逐段承压成员" in text_blob
    assert "xx渠 末尾连续承压" in text_blob
    assert "0.0315" in text_blob
    assert "总损失" in text_blob


def test_show_pressure_pipe_loss_dialog_uses_override_dialog_when_locked_row_is_editable(monkeypatch):
    QApplication.instance() or QApplication([])
    module = _load_formula_dialog_module()
    captured = {}

    def _save_override(_value):
        return None

    def _clear_override():
        return None

    class _FakeOverrideDialog:
        def __init__(self, parent, title, sections, details, on_save_override=None, on_clear_override=None):
            captured["parent"] = parent
            captured["title"] = title
            captured["sections"] = sections
            captured["details"] = details
            captured["on_save_override"] = on_save_override
            captured["on_clear_override"] = on_clear_override

    monkeypatch.setattr(module, "PressurePipeLossOverrideDialog", _FakeOverrideDialog, raising=False)

    module.show_pressure_pipe_loss_dialog(
        None,
        "行5",
        {
            "pressure_pipe_display_is_row_sum": True,
            "pressure_pipe_display_loss": 0.0253,
            "head_loss_friction": 0.0253,
            "head_loss_bend": 0.0,
            "head_loss_local": 0.0,
        },
        editable_override=True,
        manual_override_value=0.0253,
        on_save_override=_save_override,
        on_clear_override=_clear_override,
    )

    assert captured["title"] == "行5 - 倒虹吸/有压管道水头损失详情"
    assert captured["details"]["manual_total_head_loss"] == pytest.approx(0.0253)
    assert captured["on_save_override"] is _save_override
    assert captured["on_clear_override"] is _clear_override


def test_pressure_pipe_loss_column_supports_double_click_detail():
    module = _load_formula_dialog_module()

    assert "倒虹吸/有压管道水头损失" in module.DOUBLE_CLICK_COLUMNS


def test_pressure_pipe_loss_column_formula_mentions_row_level_display():
    module = _load_formula_dialog_module()
    column_info = module.COLUMN_FORMULAS["倒虹吸/有压管道水头损失"]

    assert "逐段承压成员" in column_info["description"]
    assert "xx渠 末尾连续承压" in column_info["note"]
    assert "沿程损失" in column_info["note"]
